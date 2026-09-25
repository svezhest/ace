"""EvoLib против записи апстрима EvoLib 98266b2 на живой модели (bridge/live/evolib, run.json): HMMT, первые 3 задачи
hmmt_feb_2025, 5 итераций по кругу (задачи 0, 1, 2, 0, 1 — i = kiter % data_size), 3 попытки. Запись воспроизводится
без модели (tools/record/replay): каждый запрос решателя, insight, слияний, сравнения решений и эмбеддингов побайтно
совпадает с записанным, все записанные ответы востребованы; после каждой итерации библиотека skills (IG, Future IG,
description) и insights (Future IG), лучшие решения задач, баллы, IG и улучшение — как в снимке апстрима
(steps.json)."""
import json
import threading
from dataclasses import dataclass
from pathlib import Path

import pytest

from ace.extract import BEST_ANSWER, IG
from ace.learner import swap
from ace.loop import run
from ace.memory.evolib import Library
from ace.methods.evolib import evolib
from ace.model import Model
from ace.tasks import Task
from tools.record.replay import Replayer

LIVE = Path(__file__).resolve().parents[2] / "bridge" / "live" / "evolib"
RUN = json.load(open(LIVE / "run.json"))
STEPS = []                  # после каждой итерации: (библиотека, лучшие решения, извлечённое, улучшило ли)


@dataclass
class Stream(Task):
    """Поток итераций апстрима: задачи среза по кругу."""
    def load(self, split="", size=None):
        items = super().load(split, size)[:RUN["tasks"]]
        return [items[k % len(items)] for k in range(RUN["iterations"])]


class Watched(Library):
    def learn(self, ex, extractions):
        super().learn(ex, extractions)
        [x] = extractions
        STEPS.append(dict(skills=[[r.text, r.ig, list(r.outcomes), r.doc] for r in self.skills.records()],
                          insights=[[r.text, list(r.outcomes)] for r in self.insights.records()],
                          best={q: [b.score, b.output] for q, b in self.solutions.items()},
                          ig=x.extras[IG], score=x.extras[BEST_ANSWER].score,
                          improving=self.solutions.get(x.group.question) is x.extras[BEST_ANSWER]))


@pytest.fixture(scope="module")
def replayed(tmp_path_factory):
    out = tmp_path_factory.mktemp("evolib")
    srv = Replayer(("127.0.0.1", 0), LIVE / "rec.jsonl")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    STEPS.clear()
    try:
        model = Model("ornith15-9b", f"http://127.0.0.1:{srv.server_address[1]}/v1", backend="wire")
        task = Stream("hmmt")
        run(task, swap(evolib, memory=Watched()), model, RUN["iterations"], str(out))
    finally:
        srv.shutdown()
    return srv.status(), json.load(open(out / "log.json")), task.load()


def test_requests(replayed):
    status, _, _ = replayed
    assert status["misses"] == 0 and status["unused"] == 0 and status["served"] == status["recorded"]


def test_library(replayed):
    """Библиотека и лучшие решения после каждой итерации — как снимок апстрима."""
    _, _, items = replayed
    theirs = json.load(open(LIVE / "steps.json"))
    assert len(STEPS) == len(theirs) == RUN["iterations"]
    for ours, up in zip(STEPS, theirs):
        assert ours["skills"] == up["skills"], up["iteration"]
        assert ours["insights"] == up["insights"], up["iteration"]
        assert ours["best"] == {items[int(i)]["context"]: b for i, b in up["best"].items()}, up["iteration"]


def test_iterations(replayed):
    """Лучшее решение итерации, его балл, IG и улучшение — как result run_iteration."""
    _, log, _ = replayed
    theirs = json.load(open(LIVE / "steps.json"))
    for ours, entry, up in zip(STEPS, log, theirs):
        r = up["result"]
        assert entry["output"] == r["best_solution"], up["iteration"]
        assert (ours["score"], ours["ig"], ours["improving"]) == (r["best_score"], r["IG_score"], r["is_improving"])
