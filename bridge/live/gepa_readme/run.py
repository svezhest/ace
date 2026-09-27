"""Запись GEPA: квикстарт README апстрима дословно (gepa.optimize на AIME: init_dataset целиком — 45 train, 45 val,
seed_prompt квикстарта, task_lm, max_metric_calls=150, reflection_lm), задача и рефлексия — одна модель стенда через
LiteLLM на адресе записи (OPENAI_BASE_URL прокси tools/record с --seed).

    $UPSTREAMS/.venvs/gepa/bin/python run.py OUT

От квикстарта отличаются только имя модели и наблюдатель: колбэк on_iteration_end пишет снимок состояния после
каждой итерации в OUT/steps.json (пул кандидатов, родители, оценки по примерам val, Парето-фронт, лучший по val,
число вызовов метрики, след итерации), в конце — итог optimize."""
import json
import os
import sys

UP = os.environ.get("UPSTREAMS", os.path.expanduser("~/Projects/upstreams"))
sys.path.insert(0, f"{UP}/gepa/src")

import gepa  # noqa: E402
from gepa.strategies.eval_policy import FullEvaluationPolicy  # noqa: E402

OUT = sys.argv[1]
MODEL = "openai/ornith15-9b"
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


os.makedirs(OUT, exist_ok=True)
trainset, valset, _ = gepa.examples.aime.init_dataset()

seed_prompt = {
    "system_prompt": "You are a helpful assistant. Answer the question. "
                     "Put your final answer in the format '### <answer>'"
}

result = gepa.optimize(
    seed_candidate=seed_prompt,
    trainset=trainset,
    valset=valset,
    task_lm=MODEL,
    max_metric_calls=150,
    reflection_lm=MODEL,
    callbacks=[Snapshots()],
)

print("Optimized prompt:", result.best_candidate['system_prompt'])
save(result=dict(best_idx=result.best_idx, best_candidate=result.best_candidate,
                 val_aggregate_scores=result.val_aggregate_scores, total_metric_calls=result.total_metric_calls))
