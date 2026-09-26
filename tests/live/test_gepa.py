"""GEPA против записи апстрима gepa d771eb21b5 на живой модели (bridge/live/gepa, run.json): квикстарт README на AIME,
первые 3 train и 3 val из init_dataset, max_metric_calls 18, seed 0. Запись воспроизводится без модели
(tools/record/replay) под gepa стенда: каждый запрос — решателя (DefaultAdapter) на val и минибатчах и рефлексии —
побайтно совпадает с записанным, все записанные ответы востребованы; после каждой итерации пул кандидатов
(тексты, родители, оценки по вопросам val), Парето-фронт, лучший по val, число вызовов метрики и след итерации
(родитель, минибатч, оценки до и после, принятый потомок) — как снимок апстрима (steps.json), лучший в конце — как
result.best_idx."""
import json
import os
import threading
from pathlib import Path

import pytest

from ace.learner import swap
from ace.loop import Protocol, run
from ace.methods.gepa import gepa
from ace.tasks import Task
from ace.upstream.gepa import current
from ace.wrap.gepa import Evolution
from tools.record.replay import Replayer

from . import replaying

LIVE = Path(os.environ.get("GEPA_LIVE") or Path(__file__).resolve().parents[2] / "bridge" / "live" / "gepa")
RUN = json.load(open(LIVE / "run.json"))
STEPS = []                  # снимок после каждой итерации


class Slice(Task):
    """Срез записи: первые train и val вопросов, теста нет (апстрим только оптимизирует)."""
    def load(self, split="", size=None, whole=False):
        count = {"train": RUN["train"], "val": RUN["val"]}.get(split, 0)
        return super().load(split, count, whole)[:count] if count else []


class Watched(Evolution):
    def on_pass(self, ex):
        super().on_pass(ex)
        it = self.trace[-1]
        STEPS.append(dict(
            i=self.iteration, total_num_evals=self.calls,
            candidates=[{"system_prompt": current(c.memory, ex.task)} for c in self.pool],
            parents=[c.parents for c in self.pool],
            val_subscores=[{str(j): s for j, s in c.scores.items()} for c in self.pool],
            pareto_front_valset={str(j): s for j, s in self.front.items()},
            program_at_pareto_front_valset={str(j): sorted(p) for j, p in self.at_front.items()},
            best=self.best_candidate(),
            trace=dict(selected_program_candidate=it.parent, subsample_ids=it.ids,
                       subsample_scores=it.before if it.after is not None else None,
                       new_subsample_scores=it.after, new_program_idx=it.child),
            accepted=it.child is not None))


@pytest.fixture(scope="module")
def replayed(tmp_path_factory):
    out = tmp_path_factory.mktemp("gepa")
    srv = Replayer(("127.0.0.1", 0), LIVE / "rec.jsonl")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    STEPS.clear()
    budget = RUN["max_metric_calls"]
    inner = swap(gepa.inner, protocol=Protocol(offline=True, epochs=budget))
    try:
        run(Slice("aime"), Watched(inner, budget, RUN["seed"]), replaying(srv), RUN["train"], str(out))
    finally:
        srv.shutdown()
    return srv.status(), json.load(open(out / "memory.json"))


def test_requests(replayed):
    status, _ = replayed
    assert status["misses"] == 0 and status["unused"] == 0 and status["served"] == status["recorded"]


def test_iterations(replayed):
    """Состояние после каждой итерации — как снимок апстрима (on_iteration_end)."""
    theirs = json.load(open(LIVE / "steps.json"))
    assert len(STEPS) == len(theirs["steps"])
    for ours, up in zip(STEPS, theirs["steps"]):
        for k, v in ours.items():
            assert v == up[k], (up["i"], k)


def test_best(replayed):
    """Лучший по val в конце и его текст — result апстрима; память прогона — его текст."""
    _, memory = replayed
    result = json.load(open(LIVE / "steps.json"))["result"]
    assert STEPS[-1]["best"] == result["best_idx"]
    assert STEPS[-1]["candidates"][result["best_idx"]] == result["best_candidate"]
    assert [m for m in memory if m["kind"] == "best"] == [dict(kind="best", id=result["best_idx"])]
