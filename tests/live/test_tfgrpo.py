"""TF-GRPO против записи апстрима youtu-agent c2caa53 на живой модели (bridge/live/tfgrpo, run.json): 4 вопроса
DAPO-Math-17k (первые 4 вопроса dapo_train: DAPO-Math-17k-live апстрима), группа 3, батч 4, одна эпоха, затем
итоговый агент на тех же вопросах. Запись воспроизводится без модели (tools/record/replay): каждый запрос агента
(rollout и итогового), сводок, групповых преимуществ, сверок и плана батча побайтно совпадает с записанным, все
записанные ответы востребованы; библиотека после батча — experiences апстрима, награды rollout и ответы итогового
агента — как в его БД (samples.json).

Вывод инструмента при воспроизведении берётся из записи (в нём случайный workdir апстрима, DEVIATIONS TF10), а
test_kernel сверяет вывод нашего ядра на тех же вызовах."""
import json
import re
from dataclasses import replace

import pytest

from ace.env import sandbox
from ace.env.tfgrpo import Kernel
from ace.learner import swap
from ace.loop import run
from ace.memory.tfgrpo import Experiences
from ace.methods.tfgrpo import tfgrpo
from ace.solver import tfgrpo as show
from ace.tasks import TASKS

from . import LIVE, replay, replaying, requests

RECORD = LIVE / "tfgrpo"
RUN = json.load(open(RECORD / "run.json"))
N, GROUP, BATCH = RUN["tasks"], RUN["grpo_n"], RUN["batch_size"]
STEPS = []                  # библиотека после каждого батча


class Watched(Experiences):
    def learn(self, ex, extractions):
        super().learn(ex, extractions)
        STEPS.append([r.text for r in self.records()])


def rollouts():
    """Вызовы инструмента по попыткам агента: [(аргументы, вывод апстрима), ...] у каждой попытки."""
    agent = [r["messages"] for r in requests(RECORD / "rec.jsonl") if "tools" in r]
    last = [m for m in agent if not any(len(o) > len(m) and o[:len(m)] == m for o in agent)]
    out = []
    for msgs in last:
        args = {c["id"]: c["function"]["arguments"] for m in msgs if m["role"] == "assistant" for c in m.get("tool_calls") or []}
        out.append([(args[m["tool_call_id"]], m["content"]) for m in msgs if m["role"] == "tool"])
    return out


class Recorded:
    """Ядро из записи: вызовы идут в том же порядке, что у апстрима (попытки по одной)."""
    queue = []

    def call(self, arguments):
        want, output = Recorded.queue.pop(0)
        assert arguments == want
        return output

    def close(self):
        pass


@pytest.fixture(scope="module")
def replayed(tmp_path_factory):
    out = tmp_path_factory.mktemp("tfgrpo")
    STEPS.clear()
    Recorded.queue = [c for calls in rollouts() for c in calls]
    learner = swap(tfgrpo, memory=Watched(), attempts=replace(tfgrpo.attempts, n=GROUP), every=BATCH)
    with pytest.MonkeyPatch.context() as patch, replay(RECORD / "rec.jsonl") as srv:
        patch.setattr(show, "Kernel", Recorded)
        run(TASKS["dapo"], learner, replaying(srv), N, str(out), split="train")
    return srv.status(), json.load(open(out / "log.json")), json.load(open(RECORD / "samples.json"))


def test_requests(replayed):
    status, _, _ = replayed
    assert status["misses"] == 0 and status["unused"] == 0 and status["served"] == status["recorded"]
    assert not Recorded.queue


def test_library(replayed):
    """Библиотека после батча — опыты G0, G1, ... апстрима (recorder.experiences, ExperienceCache)."""
    theirs = list(json.load(open(RECORD / "experiences.json")).values())
    assert theirs and STEPS == [theirs]


def test_rollouts(replayed):
    """Награды rollout по вопросам в порядке БД апстрима."""
    _, log, samples = replayed
    theirs = [s for s in samples if s["exp_id"].endswith("_epoch_0")]
    train = [r for r in log if r["phase"] == "train"]
    assert [r["question"] for r in train] == [s["raw_question"] for s in theirs[::GROUP]]
    assert [[e["ok"] for e in r["group"]] for r in train] == [[s["reward"] == 1.0 for s in theirs[i:i + GROUP]]
                                                          for i in range(0, len(theirs), GROUP)]


def test_final(replayed):
    """Итоговый агент: ответы и зачёт — как у run_eval апстрима (verify_func)."""
    _, log, samples = replayed
    theirs = [s for s in samples if s["exp_id"] == RUN["final_exp_id"]]
    test = [r for r in log if r["phase"] == "test"]
    assert [r["answer"] for r in test] == [s["response"] for s in theirs]
    assert [r["correct"] for r in test] == [bool(s["correct"]) for s in theirs]


@pytest.mark.skipif(not sandbox.available(), reason="нет docker-образа песочницы")
def test_kernel():
    """Наше ядро на вызовах записи даёт тот же вывод, что python_executor апстрима; workdir у каждого свой."""
    workdir = re.compile(r"/tmp/utu/python_executor/\d{8}_\d{6}_[0-9a-f]{8}")
    for calls in rollouts():
        kernel = Kernel()
        try:
            for arguments, theirs in calls:
                assert workdir.sub("W", kernel.call(arguments)) == workdir.sub("W", theirs)
        finally:
            kernel.close()
