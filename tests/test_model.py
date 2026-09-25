"""Доступ к модели: бэкенд pydantic-ai на модели-функции (исходы, отбивки инструментов, шаговый режим и Patch,
история) и провод апстрима на заглушке клиента openai (ровно messages и params, разбор reader)."""
import copy
from types import SimpleNamespace

from pydantic import BaseModel
from pydantic_ai.messages import ModelRequest, ModelResponse, SystemPromptPart, TextPart, ToolCallPart, ToolReturnPart, UserPromptPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from ace.model import Call, Model, Outcome, Patch, Reader, Step, messages, params
from ace.model.agent import EXTRA_REQUESTS


def model_of(fn):
    m = Model()
    m.agent.llm = FunctionModel(fn)
    return m


def ask(m, user="q", system="sys", temperature=0, top_p=None, **call):
    return m.ask(Call(messages(user, system), params(temperature, top_p), **call))


def add(a: int, b: int) -> str:
    """Add two numbers."""
    return str(a + b)


def responses(messages):
    return sum(isinstance(m, ModelResponse) for m in messages)


def test_answer():
    r = ask(model_of(lambda messages, info: ModelResponse(parts=[TextPart("FINAL ANSWER: 1")])))
    assert (r.output, r.outcome, r.steps) == ("FINAL ANSWER: 1", Outcome.answer, [])


def test_empty_system_not_sent():
    """Пустой системный промпт не уходит модели: у апстримов запрос — одно сообщение user."""
    seen = []
    ask(model_of(lambda messages, info: seen.append(messages) or ModelResponse(parts=[TextPart("x")])), system="")
    assert [type(p) for m in seen[0] for p in m.parts] == [UserPromptPart]


def test_rounds_run_out():
    """Модель только вызывает инструмент: после rounds + EXTRA_REQUESTS запросов ответа нет."""
    fn = lambda messages, info: ModelResponse(parts=[ToolCallPart("add", {"a": 1, "b": responses(messages)})])
    m = model_of(fn)
    r = ask(m, tools=(add,), rounds=1)
    assert r.output is None and r.outcome is Outcome.step
    assert m.usage()["calls"] == 1 + EXTRA_REQUESTS
    assert [s[2] for s in r.steps] == ["1", "2", "3"]


class Answer(BaseModel):
    value: int


def test_broken_output():
    """Вывод ни разу не проходит схему: модель сломалась."""
    fn = lambda messages, info: ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {"value": "x"})])
    r = ask(model_of(fn), reader=Reader(schema=Answer), rounds=10)
    assert r.output is None and r.outcome is Outcome.broken


def test_all_validation_errors():
    """Аргументы не той формы: в отбивке все ошибки валидации, а не первая."""
    def fn(messages, info):
        if responses(messages) == 0:
            return ModelResponse(parts=[ToolCallPart("add", {"a": "x", "b": "y"})])
        return ModelResponse(parts=[TextPart("done")])
    r = ask(model_of(fn), tools=(add,), rounds=1)
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
    r = ask(m, tools=(add,), rounds=3, on_step=on_step)
    assert r.outcome is Outcome.answer and r.output == "FINAL ANSWER: 2"
    assert [system_of(s) for s in seen] == ["sys", "sys\n\nnote 1", "sys\n\nnote 2"]
    assert got == [[Step("add", '{"a":1,"b":1}', "2")]] * 2


def test_patch_append():
    """Patch(append): сообщение в конец истории после результата инструмента, системный промпт цел."""
    m, seen = stepping()
    ask(m, tools=(add,), rounds=3, on_step=lambda new: Patch(append="lesson"))
    last = seen[1][-1]
    assert [type(p) for p in last.parts] == [ToolReturnPart, UserPromptPart] and last.parts[1].content == "lesson"
    assert [system_of(s) for s in seen] == ["sys"] * 3


def test_patch_tool_result():
    m, seen = stepping()
    ask(m, tools=(add,), rounds=3, on_step=lambda new: Patch(tool_result="lesson"))
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
    ask(model_of(fn), temperature=0.3, top_p=0.95)
    ask(model_of(fn))
    assert seen[0]["temperature"] == 0.3 and seen[0]["top_p"] == 0.95 and "top_p" not in seen[1]


def test_history_continues():
    """history — продолжение того же разговора: новое сообщение после прошлой истории, системный промпт не повторяется."""
    seen = []

    def fn(messages, info):
        seen.append([type(p).__name__ for m in messages for p in m.parts])
        return ModelResponse(parts=[TextPart(f"answer {len(seen)}")])
    m = model_of(fn)
    first = ask(m)
    second = ask(m, "again", history=first.messages)
    assert second.output == "answer 2" and m.usage()["calls"] == 2
    assert seen[1] == ["SystemPromptPart", "UserPromptPart", "TextPart", "UserPromptPart"]


def test_reader_text():
    """Разбор ответа — reader вызова; сам ответ текстом остаётся в raw."""
    r = ask(model_of(lambda messages, info: ModelResponse(parts=[TextPart("<a>x</a>")])), reader=Reader(text=str.upper))
    assert (r.output, r.raw) == ("<A>X</A>", "<a>x</a>")


def test_messages_history():
    """Сообщения с историей: системный промпт в первом запросе, прошлые реплики — история, последнее — запрос."""
    seen = []

    def fn(messages, info):
        seen.append([(type(p).__name__, p.content) for m in messages for p in m.parts])
        return ModelResponse(parts=[TextPart("ok")])
    history = [{"role": "system", "content": "s"}, {"role": "user", "content": "u1"}, {"role": "assistant", "content": "a1"},
               {"role": "user", "content": "u2"}]
    model_of(fn).ask(Call(history, params()))
    assert seen[0] == [("SystemPromptPart", "s"), ("UserPromptPart", "u1"), ("TextPart", "a1"), ("UserPromptPart", "u2")]


class Client:
    """Заглушка клиента openai: пишет аргументы create и отвечает текстом."""
    def __init__(self, text):
        self.text, self.sent = text, []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kw):
        self.sent.append(kw)
        message = SimpleNamespace(content=self.text)
        usage = SimpleNamespace(prompt_tokens=3, completion_tokens=2)
        return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason="stop")], usage=usage)


def wire(text):
    m = Model(backend="wire")
    m.wire.client = Client(text)
    return m


def test_wire_sends_exactly():
    """Провод апстрима: create ровно с messages и params вызова, ответ текстом."""
    m = wire("answer")
    call = Call([{"role": "user", "content": "q"}], {"temperature": 0, "top_p": 0.5})
    r = m.ask(call)
    assert m.wire.client.sent == [dict(model=m.name, messages=call.messages, temperature=0, top_p=0.5)]
    assert (r.output, r.raw, r.text, r.truncated) == ("answer", "answer", "answer", False)
    assert m.usage() == dict(calls=1, prompt_tokens=3, completion_tokens=2)


def test_wire_readers():
    """Разборщик апстрима — reader.text; схема без разборщика — общий разбор JSON (последний блок)."""
    assert wire("<a>x</a>").ask(Call(messages("q"), reader=Reader(text=str.upper))).output == "<A>X</A>"
    text = 'draft {"value": 1}\n```json\n{"value": 2}\n```'
    assert wire(text).ask(Call(messages("q"), reader=Reader(schema=Answer))).output == Answer(value=2)
    assert wire("no json").ask(Call(messages("q"), reader=Reader(schema=Answer))).output is None


def test_wire_tools_go_to_pydantic_ai():
    """Вызов с инструментами на проводе идёт через pydantic-ai."""
    m = wire("never")
    m.agent.llm = FunctionModel(lambda messages, info: ModelResponse(parts=[TextPart("FINAL ANSWER: 1")]))
    assert ask(m, tools=(add,), rounds=1).output == "FINAL ANSWER: 1" and not m.wire.client.sent


def test_tool_retries_do_not_end_talk():
    """Отбивки одного инструмента подряд (ModelRetry) не обрывают разговор раньше раундов."""
    from pydantic_ai import ModelRetry

    def strict(x: int) -> str:
        """Always fails."""
        raise ModelRetry("bad x")
    fn = lambda messages, info: (ModelResponse(parts=[TextPart("done")]) if responses(messages) >= 6
                                 else ModelResponse(parts=[ToolCallPart("strict", {"x": 1})]))
    r = ask(model_of(fn), tools=(strict,), rounds=10)
    assert r.output == "done" and r.outcome is Outcome.answer and len(r.steps) == 6
