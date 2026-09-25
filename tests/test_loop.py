"""Цикл: группы и температуры попыток, выбор в зачёт, вердикты и фильтр target, флаг обучения, батч и flush,
офлайн с лучшей по val версией, кэш val, новая попытка из извлечения, Patch на шаге, лог."""
import json
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, ToolCallPart, UserPromptPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from stub import TASK, Stub, right

from ace import verdict
from ace.env import Env
from ace.extract import Extraction, Extractor, Raw
from ace.learner import Learner
from ace.loop import Attempts, Experiment, best, first, run, vote
from ace.memory import Lessons
from ace.model import Model, Patch
from ace.show import Sample, Show, Whole


class Journal(list):
    """События ученика; run копирует ученика, а журнал общий с оригиналом."""
    learner = None

    def __deepcopy__(self, memo):
        return self


class Spy(Learner):
    """Ученик, который пишет события масштабов в журнал; в конце прохода журнал запоминает копию из прогона."""
    def __post_init__(self):
        super().__post_init__()
        self.events = Journal()

    def on_attempt(self, ex, episode):
        self.events.append(("attempt", ex.training, episode))

    def on_question(self, ex, group):
        self.events.append(("question", ex.training, group))
        super().on_question(ex, group)

    def on_batch(self, ex, groups):
        self.events.append(("batch", len(groups)))
        super().on_batch(ex, groups)

    def on_pass(self, ex):
        self.events.learner = self
        super().on_pass(ex)

    def of(self, kind):
        return [e for e in self.events if e[0] == kind]


def spy(**levels):
    return Spy("spy", **levels)


def last_group(learner):
    return learner.of("question")[-1][2]


def run_spy(learner, model, n=2, **kw):
    """-> (итог, ученик из прогона)."""
    summary = run(TASK, learner, model, n, **kw)
    return summary, learner.events.learner


def test_group_temperatures():
    model = Stub(lambda call: right(call) if call["temperature"] == 0 else "FINAL ANSWER: 0")
    attempts = Attempts(3, temperature=lambda k: 0 if k == 0 else 0.7, pick=first)
    summary, learner = run_spy(spy(attempts=attempts), model)
    assert [c["temperature"] for c in model.solver_calls()] == [0, 0.7, 0.7] * 2
    g = last_group(learner)
    assert len(g.episodes) == 3 and g.chosen == 0 and g.pick == "first" and not g.pass_at_k
    assert summary["correct"] == 2
    assert len(learner.of("attempt")) == 6


def test_vote():
    answers = iter(["1", "2", "2"] * 2)
    model = Stub(lambda call: f"FINAL ANSWER: {next(answers)}")
    _, learner = run_spy(spy(attempts=Attempts(3, pick=vote), group_verdict=verdict.vote), model)
    g = last_group(learner)
    assert g.vote == "2" and g.chosen == 1 and g.answer == "2"


def test_best_is_pass_at_k(tmp_path):
    model = Stub(lambda call: right(call) if call["n"] % 2 else "FINAL ANSWER: 0")
    summary, learner = run_spy(spy(attempts=Attempts(2, pick=best)), model, out=str(tmp_path))
    g = last_group(learner)
    assert g.chosen == 1 and g.pass_at_k and summary["correct"] == 2
    log = json.load(open(tmp_path / "log.json"))
    assert [r["pass_at_k"] for r in log] == [True, True] and [r["pick"] for r in log] == ["best", "best"]


@pytest.mark.parametrize("name, ok, target", [("golden", True, True), ("yes_no", True, False), ("none", None, False)])
def test_verdict_filters_target(name, ok, target):
    _, learner = run_spy(spy(verdict=getattr(verdict, name)), Stub(right), n=1)
    g = last_group(learner)
    ep = g.episodes[0]
    assert ep.ok is ok and bool(ep.target) is target and bool(g.target) is target


def test_judge():
    model = Stub(lambda call: "VERDICT: correct" if call["system"] == "You are a strict grader." else "FINAL ANSWER: 0")
    _, learner = run_spy(spy(verdict=verdict.judge), model, n=1)
    ep = last_group(learner).episodes[0]
    assert ep.ok is True and ep.target == ""


class Memory(Lessons):
    """Память, которая запоминает батчи: каждое извлечение — запись с номером вопроса."""
    def learn(self, ex, extractions):
        for x in extractions:
            self.add(x.group.question[:10])


@pytest.mark.parametrize("flush, sizes", [(False, [3]), (True, [3, 1])])
def test_batch_and_flush(flush, sizes):
    _, learner = run_spy(spy(memory=Memory(), extract=Raw(), every=3, flush=flush), Stub(), n=4)
    assert [e[1] for e in learner.of("batch")] == sizes
    assert len(learner.memory) == sum(sizes)            # без flush неполный батч отброшен


class Versions(Lessons):
    """Каждый проход — новая версия памяти: весь текст заменяется номером прохода."""
    def learn(self, ex, extractions):
        self.replace([f"version {ex.epoch}"])


def test_offline_best_by_val_and_training(tmp_path):
    """Решатель верен только при версии 0; после второго прохода val хуже — на тесте версия 0, без обучения."""
    model = Stub(lambda call: right(call) if "version 0" in call["system"] else "FINAL ANSWER: 0")
    learner = spy(memory=Versions(), extract=Raw())
    _, learner = run_spy(learner, model, n=2, epochs=2, offline=True, split="val", out=str(tmp_path))
    assert learner.memory.records()[0].text == "version 0"
    assert all(e[1] for e in learner.of("question")) and all(e[1] for e in learner.of("attempt"))
    log = json.load(open(tmp_path / "log.json"))
    assert [r["phase"] for r in log] == ["train"] * 4 + ["test"] * 2
    assert all("version 0" in c["system"] for c in model.solver_calls()[-2:])
    assert json.load(open(tmp_path / "memory.json"))[0]["text"] == "version 0"


def test_val_cache():
    """Та же память — val не пересчитывается; при случайном показе ключа нет и кэша тоже."""
    val = len(TASK.load("val"))
    for show, solves in ((Whole(), 2 + val), (Sample(1, weight=lambda r: 1), 2 + 2 * val)):
        model = Stub()
        run(TASK, Learner("x", show=show), model, 1, epochs=2, offline=True)
        assert len(model.solver_calls()) == solves + 1


class Retry(Extractor):
    """Извлечение, которое просит новую попытку с заметкой; копия в прогоне — оно само."""
    def __deepcopy__(self, memo):
        return self

    def __call__(self, ex, group, memory):
        self.again = ex.retry(memory, "try harder")
        self.training = ex.training
        return Extraction(group, [], [])


def test_retry():
    extractor, model = Retry(), Stub()
    run(TASK, Learner("x", extract=extractor, memory=Memory()), model, 1)
    assert model.solver_calls()[-1]["user"].endswith("Reflection:\ntry harder")
    assert extractor.training and extractor.again.ok is not None


def test_seam():
    """Память требует добавку, которую извлечение не даёт: сборка падает."""
    class Needs(Lessons):
        requires = frozenset({"labels"})
    with pytest.raises(ValueError, match="labels"):
        Learner("x", memory=Needs(), extract=Raw())


def test_undeclared_extras():
    class Sneaky(Extractor):
        def __call__(self, ex, group, memory):
            return Extraction(group, [], [], {"labels": None})
    with pytest.raises(ValueError, match="необъявленные"):
        run(TASK, Learner("x", extract=Sneaky(), memory=Memory()), Stub(), 1)

# шаги: Patch и флаг обучения на модели-функции


ERROR = "Traceback (most recent call last):\nZeroDivisionError: division by zero"


class Tool(Env):
    rounds, hint = 3, ""

    def __init__(self):
        def run_python(code: str) -> str:
            """Run Python code."""
            return ERROR
        self.tools = (run_python,)


class Lesson(Show):
    """После шага с ошибкой — урок в конец истории; запоминает флаг обучения попытки."""
    watches_steps = True

    def __init__(self):
        self.training = []

    def on_step(self, ex, memory, attempt, step):
        self.training.append(attempt.training)
        return Patch(append="Check the denominator.") if step.failed else None


def stepping():
    seen = []

    def fn(messages, info: AgentInfo):
        seen.append([p.content for m in messages if isinstance(m, ModelRequest) for p in m.parts if isinstance(p, UserPromptPart)])
        if sum(isinstance(m, ModelResponse) for m in messages) < 1:
            return ModelResponse(parts=[ToolCallPart("run_python", {"code": "1/0"})])
        return ModelResponse(parts=[TextPart("FINAL ANSWER: 1")])
    model = Model()
    model.agent.llm = FunctionModel(fn)
    return model, seen


def test_patch_on_step(tmp_path):
    model, seen = stepping()
    show = Lesson()
    learner = Learner("x", show=show, env=Tool())
    run(TASK, learner, model, 1, out=str(tmp_path))
    assert "Check the denominator." in seen[1]
    log = json.load(open(tmp_path / "log.json"))
    assert log[0]["group"][0]["patches"] == [dict(system=None, append="Check the denominator.", tool_result=None)]


def test_step_training_flag():
    model, _ = stepping()
    learner = Learner("x", show=Lesson(), env=Tool())
    ex = Experiment(TASK, learner, model)
    item = TASK.load("val")[0]
    ex.item = item
    ex.question(item)
    ex.training = False
    ex.question(item)
    assert learner.show.training == [True, False]


def test_report_without_log(tmp_path):
    run_dir = tmp_path / "formula4" / "x"
    run_dir.mkdir(parents=True)
    json.dump(dict(correct=1, n=2, truncated=0, calls=2, prompt_tokens=1, completion_tokens=1),
              open(run_dir / "summary.json", "w"))
    report = Path(__file__).parent.parent / "report.py"
    r = subprocess.run([sys.executable, str(report), str(tmp_path)], capture_output=True, text=True)
    assert r.returncode == 0 and "formula4/x" in r.stdout


def test_top_p_reaches_model():
    model = Stub()
    attempts = Attempts(2, temperature=lambda k: 0.3 if k == 0 else 0.7, top_p=lambda k: 0.95 if k == 0 else None)
    run(TASK, Learner("t", attempts=attempts), model, 1)
    assert [(c["temperature"], c["top_p"]) for c in model.calls] == [(0.3, 0.95), (0.7, None)]
