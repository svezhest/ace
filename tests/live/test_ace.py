"""ACE (ace) против записи апстрима ace 82709de на живой модели (bridge/live/ace, run.json): formula, online,
5 задач, окно 3. Запись воспроизводится без модели (tools/record/replay): каждый запрос нашего метода побайтно
совпадает с записанным, все записанные ответы востребованы, playbook после каждого шага и итоговый — как у апстрима,
ответы до и после обучения и число верных в тесте окон — тоже."""
import json
import threading
from dataclasses import replace
from pathlib import Path

import pytest

from ace.learner import swap
from ace.loop import run
from ace.memory.ace import SectionedPlaybook, layout
from ace.methods.ace import ace
from ace.model import Model
from ace.tasks import TASKS
from tools.record.replay import Replayer

LIVE = Path(__file__).resolve().parents[2] / "bridge" / "live" / "ace"
N, WINDOW = 5, 3
STEPS = []                  # playbook текстом после каждого обучения (run копирует ученика, память снаружи не видна)


class Watched(SectionedPlaybook):
    def learn(self, ex, extractions):
        super().learn(ex, extractions)
        STEPS.append(layout(self))


@pytest.fixture(scope="module")
def replayed(tmp_path_factory):
    out = tmp_path_factory.mktemp("ace")
    srv = Replayer(("127.0.0.1", 0), LIVE / "rec.jsonl")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    STEPS.clear()
    try:
        model = Model("ornith15-9b", f"http://127.0.0.1:{srv.server_address[1]}/v1", backend="wire")
        run(TASKS["formula"], swap(ace, protocol=replace(ace.protocol, window=WINDOW), memory=Watched()), model, N, str(out))
    finally:
        srv.shutdown()
    return srv.status(), json.load(open(out / "log.json"))


def test_requests(replayed):
    status, _ = replayed
    assert status["misses"] == 0 and status["unused"] == 0 and status["served"] == status["recorded"] == 31


def test_playbook(replayed):
    assert STEPS == [(LIVE / "playbooks" / f"step_{k}_playbook.txt").read_text() for k in range(1, N + 1)]
    assert STEPS[-1] == (LIVE / "final_playbook.txt").read_text()


def test_answers(replayed):
    _, log = replayed
    theirs = json.load(open(LIVE / "pre_train_post_train_results.json"))
    answers = {p: [r["answer"] for r in log if r["phase"] == p] for p in ("train", "post")}
    assert answers["train"] == [r["pre_train_result"]["final_answer"] for r in theirs]
    assert answers["post"] == [r["post_train_result"]["final_answer"] for r in theirs]
    correct = {p: sum(r["correct"] for r in log if r["phase"] == p) for p in ("initial", "online")}
    assert correct["initial"] == json.load(open(LIVE / "initial_test_results.json"))["test_results"]["correct"]
    assert correct["online"] == json.load(open(LIVE / "test_results.json"))["test_results"]["correct"]
