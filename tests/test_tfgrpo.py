"""TF-GRPO: контраст попыток группы (сводки -> преимущество -> сверка с библиотекой), план батча и операции
по меткам G0, G1, ..., показ, попытки и неполный батч."""
import ast
import json

from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, ToolCallPart, UserPromptPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from stub import TASK, Stub, episode, experiment, right

from ace import render
from ace.extract import OPERATIONS, Extraction
from ace.extract.tfgrpo import Contrast
from ace.loop import Group, run
from ace.memory.tfgrpo import Experiences
from ace.methods.tfgrpo import GROUP, tfgrpo
from ace.model import Model
from ace.solver import tfgrpo as solver
from ace.solver.tfgrpo import AGENT, LAST_TURN, MAX_TURNS, RETRIES, TOOL


def by_prompt(ops='[{"operation": "ADD", "content": "New: tip."}]', plan=None):
    """Ответ модели по пользовательскому промпту стадии."""
    def answer(call):
        user = call["user"]
        if user.startswith("<Working Agent Input>"):
            return "summary of " + user.split("\n")[1]
        if "<Trajectories>" in user:
            return "<Experiences>\n1. Tip: check units.\n</Experiences>"
        if "<Existing Experiences>" in user:
            return f"```json\n{ops}\n```"
        if user.startswith("<Experiences and Proposed Operations>"):
            return f"```json\n{plan if plan is not None else ops}\n```"
        return "FINAL ANSWER: 1"
    return answer


def group(oks, target="0.5"):
    eps = [episode(ok=ok, target=target, k=k) for k, ok in enumerate(oks)]
    return Group("q", eps, target=target)


def library(*texts):
    m = Experiences()
    for t in texts:
        m.add(t)
    return m


def test_contrast_partial():
    """Сводка на каждую попытку группы (все — rollout), награды 0/1; затем преимущество и сверка с библиотекой."""
    model = Stub(by_prompt())
    x = Contrast().batch(experiment(model), [group([True, True, False, True, False, False])], library("Old: one."))[0]
    assert [c["user"].split("\n")[0] for c in model.calls[:6]] == ["<Working Agent Input>"] * 6
    advantage = model.calls[6]["user"]
    assert "Attempt 1 (Reward 1.0)" in advantage and "Attempt 3 (Reward 0.0)" in advantage and "Attempt 6" in advantage
    assert "<Ground Truth>\n0.5" in advantage
    assert "[G0]. Old: one." in model.calls[7]["user"] and "1. Tip: check units." in model.calls[7]["user"]
    assert "input: A financial question" in model.calls[0]["system"]
    assert x.lessons == ["1. Tip: check units."] and x.extras[OPERATIONS] == [{"operation": "ADD", "content": "New: tip."}]


def test_contrast_skips_uniform_group():
    """С меткой группа, где все попытки верны (или все неверны), ничего не даёт — без вызовов. scored (ace_stand_group):
    попытка в зачёт в группу не входит."""
    for oks, scored in (([True] * 3, False), ([False] * 3, False), ([False, True, True], True)):
        model = Stub(by_prompt())
        x = Contrast(scored=scored).batch(experiment(model), [group(oks)], library())[0]
        assert model.calls == [] and x.extras[OPERATIONS] == [] and x.lessons == []


def test_contrast_without_label():
    """Без верного ответа в работу идёт любая группа, ответ и награды скрыты."""
    model = Stub(by_prompt())
    g = Group("q", [episode(k=k) for k in range(3)])
    Contrast().batch(experiment(model), [g], library())[0]
    assert "<Ground Truth>\n[REDACTED]" in model.calls[3]["user"] and "(Reward [REDACTED])" in model.calls[3]["user"]


def test_contrast_bad_update():
    """Сверка без JSON-списка — пустые операции."""
    model = Stub(by_prompt(ops='{"operation": "ADD"}'))
    x = Contrast().batch(experiment(model), [group([True, True, False])], library())[0]
    assert x.extras[OPERATIONS] == []


def extraction(ops):
    return Extraction(None, [], [], {OPERATIONS: ops})


def test_plan_and_labels():
    """План по операциям батча с метками G; UPDATE — новый опыт на месте старого, UPDATE чужой метки (id памяти
    модели не видны) добавляет, DELETE по метке удаляет; операция без content пропускается, как в апстриме."""
    m = library("A: a.", "B: b.", "C: c.")
    plan = json.dumps([dict(operation="UPDATE", id="G0", content="A: a2."), dict(operation="UPDATE", id="r2", content="D: d."),
                       dict(operation="DELETE", id="G2", content="obsolete"), dict(operation="DELETE", id="G1")])
    model = Stub(by_prompt(plan=plan))
    m.learn(experiment(model), [extraction([dict(operation="UPDATE", id="G1", content="B: b2.")]), extraction([])])
    table = model.calls[0]["user"]
    assert "Experience G1:\nContent: B: b.\nRelated Operations:" in table and "Experience G0:\nContent: A: a.\nNo related" in table
    assert [(r.id, r.text) for r in m.records()] == [("r4", "A: a2."), ("r2", "B: b."), ("r5", "D: d.")]
    system = AGENT.prompt(experiment(model, training=False), m, {"question": "q"}, 0).solver.call("").messages[0]["content"]
    assert system.endswith("experiences:\n[G0]. A: a2.\n[G1]. B: b.\n[G2]. D: d.")


def test_plan_retries_and_no_ops():
    """Без операций план всё равно строится (как в апстриме); JSON не разобрался — до трёх попыток."""
    model = Stub(lambda call: "no json")
    m = library("A: a.")
    m.learn(experiment(model), [extraction([])])
    assert len(model.calls) == 3 and "No batch operations." in model.calls[0]["user"] and len(m) == 1


def test_attempts_and_batch():
    """Протокол апстрима: проход по train — группа из 5 rollout при T=0.7, top_p 0.95, с инструментом и задачей с
    опытами ("None") в user; неполный батч отбрасывается; в зачёт — тест итоговым агентом, при пустой библиотеке
    он остаётся при 0.7 (поверхностная копия апстрима), задача в user как есть."""
    model = Stub(lambda call: right(call) if not call["user"].startswith("<") else by_prompt()(call))
    summary = run(TASK, tfgrpo, model, 2)
    agent = [c for c in model.calls if c["tools"]]
    assert [(c["temperature"], c["top_p"]) for c in agent] == [(0.7, 0.95)] * (2 * GROUP + 2)
    assert all(c["user"].startswith("Please solve the problem:\n") and c["user"].endswith("experiences:\nNone")
               for c in agent[:2 * GROUP])
    assert [c["user"] for c in agent[2 * GROUP:]] == [r["question"] for r in TASK.load()[:2]]
    assert agent[0]["system"].startswith(TASK.system + "\n\nSolve the following problem step by step.")
    assert summary["correct"] == 2 and summary["n"] == 2
    assert not any(c["user"].startswith("<Experiences and Proposed Operations>") for c in model.calls)
    assert render.experiences([]) == "None"


class Unreachable:
    """Клиент провода, который падает при любом обращении."""
    def __getattr__(self, name):
        raise AssertionError(f"вызов провода: {name}")


class FakeKernel:
    """Ядро попытки без песочницы: запоминает аргументы вызовов."""
    made = []

    def __init__(self):
        self.calls = []
        FakeKernel.made.append(self)

    def call(self, arguments):
        self.calls.append(arguments)
        return "2\n"

    def close(self):
        pass


def on_pydantic_ai(monkeypatch, fn):
    m = Model(backend="pydantic-ai")
    m.wire.client = Unreachable()
    m.agent.llm = FunctionModel(fn)
    FakeKernel.made = []
    monkeypatch.setattr(solver, "Kernel", FakeKernel)
    return m


def users(messages):
    return [p.content for m in messages if isinstance(m, ModelRequest) for p in m.parts if isinstance(p, UserPromptPart)]


def attempt(m):
    s = AGENT.prompt(experiment(m), library(), {"question": "q"}, 0).solver
    return s.talk(m, s.call(""))


def test_agent_on_pydantic_ai(monkeypatch):
    """На pydantic-ai попытка идёт его циклом, провод не тронут: модель видит ту же схему инструмента и параметры,
    инструмент исполняет ядро попытки, траектория — той же формы, что на проводе, итог — текст ответа."""
    seen = []

    def fn(messages, info: AgentInfo):
        seen.append(info)
        if not any(isinstance(m, ModelResponse) for m in messages):
            return ModelResponse(parts=[ToolCallPart("execute_python_code", '{"code": "print(1+1)"}', tool_call_id="c1")])
        return ModelResponse(parts=[TextPart("FINAL ANSWER: 2")])
    m = on_pydantic_ai(monkeypatch, fn)
    reply = attempt(m)
    tool = seen[0].function_tools[0]
    assert (tool.name, tool.description, tool.parameters_json_schema) == (
        "execute_python_code", TOOL["function"]["description"], TOOL["function"]["parameters"])
    assert (seen[0].model_settings["temperature"], seen[0].model_settings["top_p"]) == (0.7, 0.95)
    assert [k.calls for k in FakeKernel.made] == [['{"code": "print(1+1)"}']]
    assert reply.output == "FINAL ANSWER: 2" and not reply.truncated
    call = {"id": "c1", "type": "function", "function": {"name": "execute_python_code", "arguments": '{"code": "print(1+1)"}'}}
    assert ast.literal_eval(reply.text)[1:] == [
        {"role": "assistant", "content": None, "tool_calls": [call]},
        {"role": "tool", "tool_call_id": "c1", "content": "2\n"},
        {"role": "assistant", "content": "FINAL ANSWER: 2"}]
    assert m.wire.calls == 0


def test_agent_last_turn_and_retries(monkeypatch):
    """Предел ходов тот же: перед последним ходом — просьба ответить, вызов на последнем ходу — попытка упала;
    упавшая попытка повторяется до RETRIES раз, каждый раз с новым ядром, потом — попытка без траектории."""
    requests = []

    def fn(messages, info):
        requests.append(users(messages))
        return ModelResponse(parts=[ToolCallPart("execute_python_code", '{"code": "1"}')])
    m = on_pydantic_ai(monkeypatch, fn)
    reply = attempt(m)
    assert (reply.output, reply.text) == ("", "")
    assert len(FakeKernel.made) == RETRIES and len(requests) == RETRIES * MAX_TURNS
    assert [LAST_TURN["content"] in r for r in requests[:MAX_TURNS]] == [False] * (MAX_TURNS - 1) + [True]


def test_agent_foreign_tool_fails(monkeypatch):
    """Вызов чужого инструмента роняет попытку, как на проводе."""
    m = on_pydantic_ai(monkeypatch, lambda messages, info: ModelResponse(parts=[ToolCallPart("shell", "{}")]))
    assert attempt(m).text == "" and len(FakeKernel.made) == RETRIES
    assert all(k.calls == [] for k in FakeKernel.made)


def test_run_on_pydantic_ai(monkeypatch):
    """Обучение и тест TF-GRPO на pydantic-ai: ни одного вызова провода."""
    answer = by_prompt()

    def fn(messages, info):
        user = users(messages)[-1]
        text = right(dict(user=user)) if info.function_tools else answer(dict(user=user))
        return ModelResponse(parts=[TextPart(text)])
    m = on_pydantic_ai(monkeypatch, fn)
    summary = run(TASK, tfgrpo, m, 2)
    assert summary["correct"] == 2 and m.wire.calls == 0 and m.agent.calls > 2 * GROUP
