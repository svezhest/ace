"""Dynamic Cheatsheet против записей апстрима dynamic-cheatsheet 5cfe3c3 на живой модели (bridge/live/<метод>,
run.json): MathEquationBalancer, первые 5 вопросов после shuffle(seed=10), по записи на вариант — dc (DC-Cu), dc_rs
(DC-RS), dc_retrieval, dc_history (без исполнения кода) и dc_code (DC-Cu с кодом, апстрим в контейнере). Запись
воспроизводится без модели (tools/record/replay): каждый запрос нашего метода побайтно совпадает с записанным, все
записанные ответы востребованы; cheatsheet после каждого вопроса (у пар — что стояло в [[CHEATSHEET]]), пары,
ответы генератора, ответы в зачёт и число верных — как у апстрима.

dc_code: при воспроизведении вывод исполнения берётся из записи (у апстрима в traceback — случайное имя tempfile,
DC4), а test_sandbox сверяет вывод нашей песочницы на тех же блоках кода с записанным."""
import json
import re
import threading
from pathlib import Path

import pytest

from ace.env import sandbox
from ace.extract import SHEET
from ace.learner import swap
from ace.loop import run
from ace.memory.dc import Cheatsheet, Pairs
from ace.methods.dc import dc, dc_code, dc_history, dc_retrieval, dc_rs
from ace.model import Model
from ace.solver import dc as show
from ace.tasks import TASKS
from tools.record.replay import Replayer

LIVE = Path(__file__).resolve().parents[2] / "bridge" / "live"
N = 5
STEPS = []                  # после каждого обучения: (что стояло в [[CHEATSHEET]], память)


class WatchedSheet(Cheatsheet):
    def learn(self, ex, extractions):
        super().learn(ex, extractions)
        STEPS.append((extractions[-1].extras[SHEET], self.text))


class WatchedPairs(Pairs):
    def learn(self, ex, extractions):
        super().learn(ex, extractions)
        STEPS.append((extractions[-1].extras[SHEET], [(r.question, r.text) for r in self.records()]))


METHODS = {"dc": swap(dc, memory=WatchedSheet()), "dc_code": swap(dc_code, memory=WatchedSheet()),
           "dc_rs": swap(dc_rs, memory=WatchedPairs(sheet=True)), "dc_retrieval": swap(dc_retrieval, memory=WatchedPairs()),
           "dc_history": swap(dc_history, memory=WatchedPairs())}
RECORDED = [name for name in METHODS if (LIVE / name / "rec.jsonl").exists()]


def executed(name):
    """Блок кода -> вывод его исполнения у апстрима, из сообщений assistant записанных запросов."""
    out = {}
    for line in open(LIVE / name / "rec.jsonl"):
        for m in json.loads(json.loads(line)["request"])["messages"]:
            if m["role"] == "assistant":
                head, ran = m["content"].split(f"\n{show.FLAG}\n\n", 1)
                out[head] = ran
    return out


@pytest.fixture(scope="module", params=RECORDED)
def replayed(request, tmp_path_factory):
    name = request.param
    out = tmp_path_factory.mktemp(name)
    srv = Replayer(("127.0.0.1", 0), LIVE / name / "rec.jsonl")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    STEPS.clear()
    patch = pytest.MonkeyPatch()
    try:
        patch.setattr(show, "run_block", executed(name).__getitem__)
        model = Model("ornith15-9b", f"http://127.0.0.1:{srv.server_address[1]}/v1", backend="wire")
        run(TASKS["meb"], METHODS[name], model, N, str(out))
    finally:
        patch.undo()
        srv.shutdown()
    theirs = [json.loads(line) for line in open(LIVE / name / "outputs.jsonl")]
    return name, srv.status(), json.load(open(out / "log.json")), list(STEPS), theirs


def test_requests(replayed):
    _, status, _, _, _ = replayed
    assert status["misses"] == 0 and status["unused"] == 0 and status["served"] == status["recorded"]


def test_memory(replayed):
    """Cheatsheet после каждого вопроса (dc) или что стояло в [[CHEATSHEET]] и пары (сырой вопрос, ответ генератора)."""
    name, _, _, steps, theirs = replayed
    assert [sheet for sheet, _ in steps] == [t["steps"][0]["current_cheatsheet"] for t in theirs]
    if name in ("dc", "dc_code"):
        assert [memory for _, memory in steps] == [t["final_cheatsheet"] for t in theirs]
    else:
        assert [sheet for sheet, _ in steps] == [t["final_cheatsheet"] for t in theirs]
        assert steps[-1][1] == [(t["raw_input"], t["final_output"]) for t in theirs]


def test_answers(replayed):
    _, _, log, _, theirs = replayed
    assert [r["output"] for r in log] == [t["final_output"] for t in theirs]
    assert [r["answer"] for r in log] == [t["final_answer"] for t in theirs]
    assert [r["question"] for r in log] == [t["raw_input"] for t in theirs]


def test_correct(replayed):
    """Число верных — как у eval_equation_balancer апстрима в его прогоне (run.json)."""
    name, _, log, _, _ = replayed
    assert sum(r["correct"] for r in log) == json.load(open(LIVE / name / "run.json"))["correct"]


@pytest.mark.skipif(not sandbox.available(), reason="нет docker-образа песочницы")
def test_sandbox():
    """Наша песочница на блоках кода записи dc_code даёт тот же вывод, что python3 апстрима; в traceback вместо
    случайного файла tempfile — наш файл (DC4)."""
    ran = executed("dc_code")
    assert ran
    for head, theirs in ran.items():
        assert show.run_block(head).strip() == re.sub(r"/tmp/tmp\w+\.py", show.CODE_FILE, theirs)
