"""Событие шага на модели-функции: правило SCOPE, выученное на шаге с ошибкой, в системном промпте
следующего шага; хук инжекта прототипа после отбивки."""
import json

from pydantic_ai.messages import ModelRequest, ModelResponse, SystemPromptPart, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from ace import inject
from ace.env import Env
from ace.loop import Solver, run, swap
from ace.methods import proto, scope
from ace.model import Model
from ace.tasks import TASKS

RULE = "Guard the division against zero."
ARGS = {"Proposal": {"update_text": RULE, "rationale": "crash", "confidence": "high"},
        "Classification": {"is_duplicate": False, "scope": "strategic", "confidence": 0.9, "domain": "error_handling"},
        "Selection": {"selected_index": 0},
        "TypedReflection": {"helpful": [], "harmful": [], "lessons": [
            {"kind": "procedure", "when": "dividing", "text": RULE}]}}


def harness():
    """Модель: два вызова run_python, оба падают, затем ответ; схемы обновления заполнены ARGS."""
    systems = []

    def fn(messages, info: AgentInfo):
        if info.output_tools:
            t = info.output_tools[0]
            args = ARGS.get((t.parameters_json_schema or {}).get("title", ""))
            if args is None:
                args = {"ops": []} if "ops" in json.dumps(t.parameters_json_schema) else {"lessons": ["Check units."], "helpful": [], "harmful": []}
            return ModelResponse(parts=[ToolCallPart(t.name, args)])
        if "merge" in [t.name for t in info.function_tools] and not any(isinstance(m, ModelResponse) for m in messages):
            # куратор прототипа с инструментами: одна запись
            return ModelResponse(parts=[ToolCallPart("add", {"kind": "procedure", "when": "dividing", "text": RULE})])
        if any(t.name == "run_python" for t in info.function_tools):
            systems.append(next(p.content for m in messages if isinstance(m, ModelRequest) for p in m.parts
                                if isinstance(p, SystemPromptPart)))
            n = sum(isinstance(m, ModelResponse) for m in messages)
            if n < 2:
                return ModelResponse(parts=[ToolCallPart("run_python", {"code": f"print(1/0) # {n}"})])
        return ModelResponse(parts=[TextPart("FINAL ANSWER: 1.00")])

    def run_python(code: str) -> str:
        """Run Python code."""
        return "Traceback (most recent call last):\nZeroDivisionError: division by zero"

    class Broken(Env):
        rounds, hint, tools = 3, "", (run_python,)

    model = Model()
    model.llm = FunctionModel(fn)
    return model, Broken(), systems


def test_scope_rule_on_next_step(tmp_path):
    model, env, systems = harness()
    run(TASKS["formula"], swap(scope, solver=Solver(env=env)), model, 2, str(tmp_path))
    guideline = ["## Learned Guideline:\n" + RULE in s for s in systems]
    assert guideline == [False, True, True, False, True, True]
    # правило первой задачи стало strategic и видно со старта второй
    assert "### Error Handling:\n- " + RULE in systems[3]
    memory = json.load(open(tmp_path / "memory.json"))
    assert [r["kind"] for r in memory] == ["strategic", "tactical", "tactical", "tactical"]
    assert {r["text"] for r in memory} == {RULE}


def test_proto_hook_after_failure(tmp_path):
    model, env, systems = harness()
    related = inject.show(("procedure", "insight"), line=inject.dashed, before="Entries related to the last error:\n", head="")
    method = swap(proto, inject=inject.hooked(proto.inject, related, on=inject.on_failure), solver=Solver(env=env))
    run(TASKS["formula"], method, model, 2, str(tmp_path))
    assert ["Entries related to the last error:\n- " + RULE in s for s in systems] == [False] * 4 + [True] * 2
    assert "Entries you can read with read(path):\nskills/r1  dividing" in systems[3]
    memory = json.load(open(tmp_path / "memory.json"))
    assert [(r["kind"], r["id"]) for r in memory] == [("episode", "e1"), ("procedure", "r1"), ("episode", "e2"), ("procedure", "r2")]
