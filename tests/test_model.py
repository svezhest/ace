"""Прогон модели на модели-функции: исходы, отбивки инструментов, шаговый режим."""
from pydantic import BaseModel
from pydantic_ai.messages import ModelRequest, ModelResponse, SystemPromptPart, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from ace.model import EXTRA_REQUESTS, Model, Outcome


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


def test_step_mode():
    """on_step после шага с инструментом дописывает текст к системному промпту следующего запроса."""
    systems = []

    def fn(messages, info: AgentInfo):
        systems.append(next(p.content for m in messages if isinstance(m, ModelRequest) for p in m.parts
                            if isinstance(p, SystemPromptPart)))
        if responses(messages) < 2:
            return ModelResponse(parts=[ToolCallPart("add", {"a": 1, "b": 1})])
        return ModelResponse(parts=[TextPart("FINAL ANSWER: 2")])

    seen = []
    on_step = lambda new: seen.append(new) or f"note {len(seen)}"
    r = model_of(fn).run("sys", "q", tools=(add,), rounds=3, on_step=on_step)
    assert r.outcome is Outcome.answer and r.output == "FINAL ANSWER: 2"
    assert systems == ["sys", "sys\n\nnote 1", "sys\n\nnote 2"]
    assert seen == [[("add", '{"a":1,"b":1}', "2")]] * 2
