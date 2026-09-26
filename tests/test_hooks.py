"""Хуки по ошибкам (Hooks) и гибриды: уроки модели (уверенные, trigger из текста ошибки, показ не помогших),
уроки из траектории, память хуков (тот же trigger — новая запись, исходы показа, отсев), показ после ошибки
Patch в конец с исходом по следующему шагу, показ в системном промпте с исходом по попытке; ace_stand_bo2 (Best-of-2 с
селектором), ace_stand_opt (предел с оптимизатором вместо отсева), ace_stand_group (контраст TF-GRPO и куратор ACE)."""
import json

from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, ToolCallPart, UserPromptPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from stub import TASK, Stub, episode, experiment, right

from ace.env import Env
from ace.extract import LABELS, LESSONS, TRIGGER, Extraction, Labels
from ace.extract.ace import Reflection
from ace.extract.hooks import HookLesson, HookLessons, by_model, by_trajectory, error_kind
from ace.memory.counters import count
from ace.memory.hooks import HookBook
from ace.wrap.hooks import Hooks
from ace.learner import Learner
from ace.loop import Attempt, Group, Prompt, run
from ace.memory.ace import Ops
from ace.memory.ace import CappedPlaybook
from ace.methods.hybrids import ace_stand_bo2, ace_stand_group, ace_stand_hooks, ace_stand_opt
from ace.model import Model, Patch, Step

ERROR = "Traceback (most recent call last):\nZeroDivisionError: division by zero"
FAIL = Step("run_python", '{"code": "1/0"}', ERROR)
FINE = Step("run_python", '{"code": "1/2"}', "0.5")


def failed_episode(steps, fired=()):
    ep = episode("1", ok=False, target="2")
    ep.steps, ep.fired = list(steps), list(fired)
    return ep


def hooks_book(*pairs):
    m = HookBook()
    for trigger, text in pairs:
        m.add(text, trigger=trigger)
    return m


def test_by_model_keeps_confident_triggers_from_errors():
    r = HookLessons(hooks=[HookLesson(trigger="ZeroDivisionError", lesson="Check the denominator.", confidence="high"),
                           HookLesson(trigger="KeyError", lesson="x", confidence="high"),
                           HookLesson(trigger="division by zero", lesson="y", confidence="medium")])
    model = Stub(schemas={"HookLessons": r})
    memory = hooks_book(("zerodivisionerror", "old lesson"))
    out = by_model(experiment(model), failed_episode([FAIL, FINE], fired=[("h1", False)]), memory)
    assert out == [("ZeroDivisionError", "Check the denominator.")]
    user = model.calls[0]["user"]
    assert "- trigger: zerodivisionerror\n  lesson: old lesson" in user and "1. run_python" in user


def test_by_trajectory():
    assert error_kind(ERROR) == "ZeroDivisionError"
    assert error_kind("Error: something went wrong") == "Error: something went wrong"
    out = by_trajectory(experiment(), failed_episode([FAIL, FINE, FAIL]), HookBook())
    assert out == [("ZeroDivisionError", 'Earlier the same error was followed by a call that worked:\nrun_python {"code": "1/2"}')]


def test_hook_book():
    m = hooks_book(("ZeroDivisionError", "a"))
    x = lambda texts, triggers, helpful=(), harmful=(): Extraction(None, texts, [], {TRIGGER: triggers, LABELS: Labels(list(helpful), list(harmful))})
    m.learn(experiment(), [x(["a"], ["zerodivisionerror"], helpful=["h1"])])
    assert [(r.id, r.text, r.helpful) for r in m.records()] == [("h1", "a", 1)]
    m.learn(experiment(), [x(["b", "c"], ["ZeroDivisionError", "KeyError"])])
    assert [(r.id, r.text, r.helpful) for r in m.records()] == [("h2", "b", 0), ("h3", "c", 0)]
    m.learn(experiment(), [x([], [], harmful=["h2", "h2", "h3"], helpful=["h3"])])
    assert [r.id for r in m.records()] == ["h3"]
    assert HookBook(prune=None).requires == frozenset({LESSONS, TRIGGER})


def step(h, a, s, turn):
    """Шаг s из ответа модели номер turn, как его отдаёт цикл."""
    a.steps.append(s)
    a.turns.append(turn)
    return h.on_step(experiment(), a, s)


def test_after_error_patch_and_outcome():
    h = Hooks(Learner("x"), learn="raw")
    h.hooks.add("Check the denominator.", trigger="ZeroDivisionError")
    a = Attempt("q", 0, True, Prompt(), "SYS")
    assert step(h, a, FAIL, 0) == Patch(append="Known fix for this error:\n- Check the denominator.")
    assert step(h, a, FINE, 1) is None and a.fired == [("h1", True)]
    step(h, a, FAIL, 2)
    step(h, a, FAIL, 3)
    assert a.fired == [("h1", True), ("h1", False)]


def test_outcome_by_next_response():
    """Хук показан после всех шагов ответа: второй шаг того же ответа его не видел, исход — по первому шагу
    следующего ответа; ошибка вызова инструмента хук не показывает."""
    h = Hooks(Learner("x"), learn="raw")
    h.hooks.add("Check the denominator.", trigger="ZeroDivisionError")
    a = Attempt("q", 0, True, Prompt(), "SYS")
    step(h, a, FAIL, 0)
    step(h, a, FINE, 0)
    assert a.fired == []
    step(h, a, FAIL, 1)
    assert a.fired == [("h1", False)]
    assert step(h, Attempt("q", 0, True, Prompt(), "SYS"), Step("run_python", "{}", "Error: ZeroDivisionError"), 0) is None


def test_system_variant():
    h = Hooks(Learner("x"), learn="raw", show="system")
    h.hooks.add("Check the denominator.", trigger="ZeroDivisionError")
    p = h.prompt(experiment(), {"question": "q"}, 0)
    assert "Known fixes for tool errors" in p.system and "- trigger: ZeroDivisionError" in p.system and p.shown == ["h1"]
    a = Attempt("q", 0, True, p, "SYS")
    a.steps.append(FAIL)
    assert h.on_step(experiment(), a, FAIL) is None
    ep = failed_episode([FAIL])
    ep.prompt = p
    h.on_attempt(experiment(), ep)
    assert ep.fired == [("h1", False)]


class Tool(Env):
    rounds, hint = 3, ""

    def __init__(self):
        def run_python(code: str) -> str:
            """Run Python code."""
            return ERROR
        self.tools = (run_python,)


def test_hooks_run(tmp_path):
    seen = []

    def fn(messages, info: AgentInfo):
        seen.append([p.content for m in messages if isinstance(m, ModelRequest) for p in m.parts if isinstance(p, UserPromptPart)])
        if sum(isinstance(m, ModelResponse) for m in messages) < 2:
            return ModelResponse(parts=[ToolCallPart("run_python", {"code": "1/0"})])
        return ModelResponse(parts=[TextPart("FINAL ANSWER: 1")])
    model = Model()
    model.agent.llm = FunctionModel(fn)
    h = Hooks(Learner("x", env=Tool()), learn="raw", prune=3)
    h.hooks.add("Check the denominator.", trigger="ZeroDivisionError")
    run(TASK, h, model, 1, out=str(tmp_path))
    assert "Known fix for this error:\n- Check the denominator." in seen[1][-1]
    log = json.load(open(tmp_path / "log.json"))
    assert log[0]["group"][0]["fired"] == [["h1", False]]
    hooks = [r for r in json.load(open(tmp_path / "memory.json")) if r["kind"] == "hook"]
    assert [(r["id"], r["harmful"]) for r in hooks] == [("h1", 1)]


def test_ace_hooks_levels():
    assert ace_stand_hooks.env.tools and ace_stand_hooks.watches_steps and ace_stand_hooks.name == "ace_stand_hooks"


def test_ace_bo2_selects():
    lessons = iter([["first"], ["second"]])
    model = Stub(lambda call: "2", schemas={"Reflection": lambda call: Reflection(lessons=next(lessons))})
    ep = episode("1", ok=True, target="1")
    x = ace_stand_bo2.extract(experiment(model), Group("q", [ep], target="1"), ace_stand_bo2.memory)
    assert x.lessons == ["second"] and "## 1\n- first\n\n## 2\n- second" in model.calls[2]["user"]
    assert [c["temperature"] for c in model.calls] == [0.7, 0.7, 0]


def test_ace_opt_caps_playbook():
    optimizer = lambda call: (json.dumps(dict(consolidation=[[1, 2, 3]])) if "rule optimization analyzer" in call["user"]
                              else json.dumps(dict(rule="merged", rationale="m")))
    model = Stub(optimizer, schemas={"Ops": Ops(ops=[dict(op="ADD", text=f"bullet {i}") for i in range(11)])})
    m = CappedPlaybook()
    m.add("kept")
    count(m, ["r1"], [])
    m.learn(experiment(model), [Extraction(None, ["l"], [], {LABELS: Labels()})])
    texts = [r.text for r in m.records()]
    assert len(texts) == 10 and texts[-1] == "merged"
    assert texts[0] == "kept" and m.get("r1").helpful == 1         # нетронутый пункт — со своими счётчиками
    assert ace_stand_opt.memory.requires == frozenset({LESSONS})


def test_ace_group_levels():
    """ace_stand_group: в зачёт попытка при T = 0, группа из 3 при T = 0.7; извлечение без операций, память без отсева."""
    assert [ace_stand_group.attempts.temperature(k) for k in range(ace_stand_group.attempts.n)] == [0, 0.7, 0.7, 0.7]
    assert ace_stand_group.extract.gives == frozenset() and ace_stand_group.memory.requires == frozenset({LESSONS})


def test_ace_group_contrast_to_curator(tmp_path):
    """Группа верна частично: сводки трёх попыток группы (не той, что в зачёт), преимущество, опыт — уроком куратору
    ACE; сверки с библиотекой TF-GRPO нет. Группа верна целиком — вызовов обучения нет."""
    def answer(call):
        user = call["user"]
        if user.startswith("<Working Agent Input>"):
            return "summary"
        if "<Trajectories>" in user:
            return "<Experiences>\n1. Tip: check units.\n</Experiences>"
        return right(call) if call["temperature"] == 0 or call["n"] % 2 else "FINAL ANSWER: 0"
    model = Stub(answer, schemas={"Ops": Ops(ops=[dict(op="ADD", text="Check units.")])})
    run(TASK, ace_stand_group, model, 1, str(tmp_path))
    users = [c["user"] for c in model.calls]
    assert sum(u.startswith("<Working Agent Input>") for u in users) == 3
    assert not any("<Existing Experiences>" in u for u in users)
    assert "- 1. Tip: check units." in users[-1]
    assert [r["text"] for r in json.load(open(tmp_path / "memory.json"))] == ["Check units."]
    model = Stub(right, schemas={"Ops": Ops(ops=[])})
    run(TASK, ace_stand_group, model, 1, str(tmp_path))
    assert len(model.calls) == 4
