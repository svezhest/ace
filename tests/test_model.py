"""Прогон модели на модели-функции: исходы, отбивки инструментов, шаговый режим и Patch."""
import copy

from pydantic import BaseModel
from pydantic_ai.messages import ModelRequest, ModelResponse, SystemPromptPart, TextPart, ToolCallPart, ToolReturnPart, UserPromptPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from ace.model import EXTRA_REQUESTS, Model, Outcome, Patch, Step


def model_of(fn):
    m = Model()
    m.llm = FunctionModel(fn)
    return m


def add(a: int, b: int) -> str:
    """Add two numbers."""
    return str(a + b)


def responses(messages):
    return sum(isinstance(m, ModelResponse) for m in messages)


def test_answer():
    r = model_of(lambda messages, info: ModelResponse(parts=[TextPart("FINAL ANSWER: 1")])).run("sys", "q")
    assert (r.output, r.outcome, r.steps) == ("FINAL ANSWER: 1", Outcome.answer, [])


def test_rounds_run_out():
    """Модель только вызывает инструмент: после rounds + EXTRA_REQUESTS запросов ответа нет."""
    fn = lambda messages, info: ModelResponse(parts=[ToolCallPart("add", {"a": 1, "b": responses(messages)})])
    m = model_of(fn)
    r = m.run("sys", "q", tools=(add,), rounds=1)
    assert r.output is None and r.outcome is Outcome.step
    assert m.calls == 1 + EXTRA_REQUESTS
    assert [s[2] for s in r.steps] == ["1", "2", "3"]


class Answer(BaseModel):
    value: int


def test_broken_output():
    """Вывод ни разу не проходит схему: модель сломалась."""
    fn = lambda messages, info: ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {"value": "x"})])
    r = model_of(fn).run("sys", "q", output=Answer, rounds=10)
    assert r.output is None and r.outcome is Outcome.broken


def test_all_validation_errors():
    """Аргументы не той формы: в отбивке все ошибки валидации, а не первая."""
    def fn(messages, info):
        if responses(messages) == 0:
            return ModelResponse(parts=[ToolCallPart("add", {"a": "x", "b": "y"})])
        return ModelResponse(parts=[TextPart("done")])
    r = model_of(fn).run("sys", "q", tools=(add,), rounds=1)
    [(name, _, result)] = r.steps
    assert name == "add" and result.startswith("Error: ")
    assert result.count("valid integer") == 2


def stepping():
    """Модель: два вызова add, затем ответ; запоминает, что видела перед каждым запросом."""
    seen = []

    def fn(messages, info: AgentInfo):
        seen.append(copy.deepcopy(messages))
        if responses(messages) < 2:
            return ModelResponse(parts=[ToolCallPart("add", {"a": 1, "b": 1})])
        return ModelResponse(parts=[TextPart("FINAL ANSWER: 2")])
    return model_of(fn), seen


def system_of(messages):
    return next(p.content for m in messages if isinstance(m, ModelRequest) for p in m.parts if isinstance(p, SystemPromptPart))


def test_patch_system():
    """Patch(system) переписывает системный промпт следующего запроса; история та же."""
    m, seen = stepping()
    got = []
    on_step = lambda new: got.append(new) or Patch(system=f"sys\n\nnote {len(got)}")
    r = m.run("sys", "q", tools=(add,), rounds=3, on_step=on_step)
    assert r.outcome is Outcome.answer and r.output == "FINAL ANSWER: 2"
    assert [system_of(s) for s in seen] == ["sys", "sys\n\nnote 1", "sys\n\nnote 2"]
    assert got == [[Step("add", '{"a":1,"b":1}', "2")]] * 2


def test_patch_append():
    """Patch(append): сообщение в конец истории после результата инструмента, системный промпт цел."""
    m, seen = stepping()
    m.run("sys", "q", tools=(add,), rounds=3, on_step=lambda new: Patch(append="lesson"))
    last = seen[1][-1]
    assert [type(p) for p in last.parts] == [ToolReturnPart, UserPromptPart] and last.parts[1].content == "lesson"
    assert [system_of(s) for s in seen] == ["sys"] * 3


def test_patch_tool_result():
    m, seen = stepping()
    m.run("sys", "q", tools=(add,), rounds=3, on_step=lambda new: Patch(tool_result="lesson"))
    assert seen[1][-1].parts[0].content == "2\n\nlesson"


def test_patch_merge():
    p = Patch(system="a", append="x").merge(Patch(append="y", tool_result="t"))
    assert p == Patch(system="a", append="x\n\ny", tool_result="t")


def test_top_p():
    """top_p уходит в настройки запроса, только если задан."""
    seen = []

    def fn(messages, info):
        seen.append(dict(info.model_settings))
        return ModelResponse(parts=[TextPart("FINAL ANSWER: 1")])
    model_of(fn).run("sys", "q", temperature=0.3, top_p=0.95)
    model_of(fn).run("sys", "q")
    assert seen[0]["temperature"] == 0.3 and seen[0]["top_p"] == 0.95 and "top_p" not in seen[1]
