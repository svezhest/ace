"""Запись GEPA: квикстарт README апстрима как есть (gepa.optimize на AIME: init_dataset, seed_prompt, DefaultAdapter
задачи, рефлексия моделью), задача и рефлексия — одна модель стенда через LiteLLM на адресе записи.

    $UPSTREAMS/.venvs/gepa/bin/python run.py OUT [TRAIN VAL MAX_METRIC_CALLS]
    (адрес модели — OPENAI_BASE_URL записывающего прокси tools/record с --seed; по готовой записи — tools/record/replay:
    прогон без модели, те же запросы и снимки)

Отличия от квикстарта — только конфиг запуска, код апстрима не тронут:
    срез           первые TRAIN (3) train и VAL (3) val из init_dataset() апстрима (train и val — половины
                   AI-MO/aimo-validation-aime после shuffle Random(0))
    модель         task_lm и reflection_lm — openai/ornith15-9b (адрес — OPENAI_BASE_URL, его читает LiteLLM)
    адаптер        DefaultAdapter(model, max_litellm_workers=1) вместо task_lm=: тот же адаптер, что строит optimize,
                   только запросы задачи по одному (параллелизм 1)
    бюджет         max_metric_calls=MAX_METRIC_CALLS (18) вместо 150; seed=0 — умолчание optimize
Снимок после каждой итерации (on_iteration_end) и в конце — OUT/steps.json: пул кандидатов, родители, оценки по
примерам val, Парето-фронт, лучший по val, число вызовов метрики, след итерации (родитель, минибатч, оценки до и
после)."""
import json
import os
import sys

UP = os.environ.get("UPSTREAMS", os.path.expanduser("~/Projects/upstreams"))
sys.path.insert(0, f"{UP}/gepa/src")

import gepa  # noqa: E402
from gepa.adapters.default_adapter.default_adapter import DefaultAdapter  # noqa: E402
from gepa.strategies.eval_policy import FullEvaluationPolicy  # noqa: E402

OUT = sys.argv[1]
TRAIN, VAL, BUDGET = (int(x) for x in sys.argv[2:5]) if len(sys.argv) > 4 else (3, 3, 18)
MODEL = "openai/ornith15-9b"
SEED = 0
STEPS = []


def snapshot(state, **more):
    """Состояние апстрима в сравнимом виде: множества — списками по возрастанию."""
    trace = state.full_program_trace[-1] if state.full_program_trace else {}
    return dict(
        i=state.i, total_num_evals=state.total_num_evals,
        candidates=[dict(c) for c in state.program_candidates],
        parents=[list(p) for p in state.parent_program_for_candidate],
        val_subscores=[{str(k): v for k, v in s.items()} for s in state.prog_candidate_val_subscores],
        pareto_front_valset={str(k): v for k, v in state.pareto_front_valset.items()},
        program_at_pareto_front_valset={str(k): sorted(v) for k, v in state.program_at_pareto_front_valset.items()},
        best=FullEvaluationPolicy().get_best_program(state),
        trace={k: trace.get(k) for k in ("selected_program_candidate", "subsample_ids", "subsample_scores",
                                         "new_subsample_scores", "new_program_idx")},
        **more)


class Snapshots:
    def on_iteration_end(self, event):
        STEPS.append(snapshot(event["state"], accepted=event["proposal_accepted"]))
        save()


def save(**more):
    with open(os.path.join(OUT, "steps.json"), "w") as f:
        json.dump(dict(steps=STEPS, **more), f, ensure_ascii=False, indent=1)


def main():
    os.makedirs(OUT, exist_ok=True)
    trainset, valset, _ = gepa.examples.aime.init_dataset()
    trainset, valset = trainset[:TRAIN], valset[:VAL]

    seed_prompt = {
        "system_prompt": "You are a helpful assistant. Answer the question. "
                         "Put your final answer in the format '### <answer>'"
    }
    result = gepa.optimize(
        seed_candidate=seed_prompt,
        trainset=trainset,
        valset=valset,
        adapter=DefaultAdapter(model=MODEL, max_litellm_workers=1),
        max_metric_calls=BUDGET,
        reflection_lm=MODEL,
        callbacks=[Snapshots()],
        seed=SEED,
    )
    save(result=dict(best_idx=result.best_idx, best_candidate=result.best_candidate,
                     val_aggregate_scores=result.val_aggregate_scores, total_metric_calls=result.total_metric_calls))
    print("best", result.best_idx, result.val_aggregate_scores, flush=True)


if __name__ == "__main__":
    main()
