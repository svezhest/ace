"""Хуки по ошибкам инструментов на модели-функции: урок попадает в промпт после шага с той же ошибкой,
исходы показов идут в счётчики, не помогший хук переписывается рефлексией."""
import json

import pytest
from pydantic_ai.messages import ModelRequest, ModelResponse, SystemPromptPart, TextPart, ToolCallPart, UserPromptPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from ace.env import Env
from ace.loop import Solver, run, swap
from ace.methods import METHODS, proto
from ace.methods.hybrids import hooks
from ace.model import Model
from ace.tasks import TASKS

LESSON = "Check the denominator is nonzero before dividing."
REVISED = "Revised: print the denominator first."
ERROR = "Traceback (most recent call last):\nZeroDivisionError: division by zero"


def harness(fail_always):
    """Модель: две попытки run_python (первая делит на ноль), затем ответ; рефлексия хуков предлагает урок,
    а если ей показали не помогший урок — переписанный."""
    systems = []

    def fn(messages, info: AgentInfo):
        user = " ".join(p.content for m in messages if isinstance(m, ModelRequest) for p in m.parts
                        if isinstance(p, UserPromptPart) and isinstance(p.content, str))
        if info.output_tools:
            t = info.output_tools[0]
            title = (t.parameters_json_schema or {}).get("title", "")
            if title == "HookLessons":
                lesson = REVISED if "lesson: Check" in user else LESSON
                args = {"hooks": [{"trigger": "ZeroDivisionError", "lesson": lesson, "confidence": "high"}]}
            elif title == "TypedReflection":
                args = {"helpful": [], "harmful": [], "lessons": []}
            else:
                args = {"ops": []} if "ops" in json.dumps(t.parameters_json_schema) else {"lessons": [], "helpful": [], "harmful": []}
            return ModelResponse(parts=[ToolCallPart(t.name, args)])
        if any(t.name == "run_python" for t in info.function_tools):
            systems.append(next(p.content for m in messages if isinstance(m, ModelRequest) for p in m.parts
                                if isinstance(p, SystemPromptPart)))
            n = sum(isinstance(m, ModelResponse) for m in messages)
            if n < 2:
                return ModelResponse(parts=[ToolCallPart("run_python", {"code": f"print(1/{n})"})])
        return ModelResponse(parts=[TextPart("FINAL ANSWER: 1.00")])

    def run_python(code: str) -> str:
        """Run Python code."""
        return ERROR if "1/0" in code or fail_always else "1.0"

    class Python(Env):
        rounds, hint, tools = 3, "", (run_python,)

    model = Model()
    model.llm = FunctionModel(fn)
    return model, Python(), systems


def hooks_after(name, tmp_path, fail_always=False):
    model, env, systems = harness(fail_always)
    method = hooks(proto, "keep", prune=None) if name == "keep" else METHODS[name]
    run(TASKS["formula"], swap(method, solver=Solver(env=env)), model, 5, str(tmp_path / name))
    memory = json.load(open(tmp_path / name / "memory.json"))
    return ["Known fix" in s for s in systems], [r for r in memory if r["kind"] == "hook"]


# по задаче три запроса решателя; в первой задаче хука ещё нет, дальше он показан после шага с ошибкой
SHOWN = [False, False, False] + [False, True, True] * 4


@pytest.mark.parametrize("name", ["ace_hooks", "proto_hooks", "keep"])
def test_model_hooks(name, tmp_path):
    shown, hooks_ = hooks_after(name, tmp_path)
    assert shown == SHOWN
    assert hooks_ == [dict(id="r1", text=LESSON, kind="hook", trigger="ZeroDivisionError", helpful=4, harmful=0)]


def test_raw_hooks(tmp_path):
    shown, hooks_ = hooks_after("proto_hooks_raw", tmp_path)
    assert shown == SHOWN
    assert hooks_ == [dict(id="r1", kind="hook", trigger="ZeroDivisionError", helpful=4, harmful=0,
                           text='Earlier the same error was followed by a call that worked:\nrun_python {"code":"print(1/1)"}')]


def test_missed_hook_rewritten(tmp_path):
    """Ошибка повторяется: показ вредный, рефлексия видит хук и переписывает его, счётчики с нуля."""
    shown, hooks_ = hooks_after("proto_hooks", tmp_path, fail_always=True)
    assert shown == SHOWN
    assert [(h["helpful"], h["harmful"]) for h in hooks_] == [(0, 0)]
    assert hooks_[0]["text"] in (LESSON, REVISED)
