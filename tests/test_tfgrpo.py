"""TF-GRPO: контраст попыток группы (сводки -> преимущество -> сверка с библиотекой), план батча и операции
по меткам G0, G1, ..., показ, попытки и неполный батч."""
import json

from stub import TASK, Stub, episode, right

from ace import render
from ace.extract import OPERATIONS, Extraction
from ace.extract.tfgrpo import Contrast
from ace.loop import Group, run
from ace.memory.tfgrpo import Library
from ace.methods.tfgrpo import GROUP, tfgrpo
from ace.show.tfgrpo import EXPERIENCES


class Ex:
    task, training = TASK, True

    def __init__(self, model):
        self.model = model


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
    m = Library()
    for t in texts:
        m.add(t)
    return m


def test_contrast_partial():
    """Попытка в зачёт (0) не входит в группу для обучения; сводка на каждую из остальных, награды 0/1."""
    model = Stub(by_prompt())
    x = Contrast().batch(Ex(model), [group([True, True, False, True, False, False])], library("Old: one."))[0]
    assert [c["user"].split("\n")[0] for c in model.calls[:5]] == ["<Working Agent Input>"] * 5
    advantage = model.calls[5]["user"]
    assert "Attempt 1 (Reward 1.0)" in advantage and "Attempt 2 (Reward 0.0)" in advantage and "Attempt 6" not in advantage
    assert "<Ground Truth>\n0.5" in advantage
    assert "[G0]. Old: one." in model.calls[6]["user"] and "1. Tip: check units." in model.calls[6]["user"]
    assert "input: A financial question" in model.calls[0]["system"]
    assert x.lessons == ["1. Tip: check units."] and x.extras[OPERATIONS] == [{"operation": "ADD", "content": "New: tip."}]


def test_contrast_skips_uniform_group():
    """С меткой группа, где все попытки для обучения верны (или все неверны), ничего не даёт — без вызовов;
    попытка в зачёт не считается."""
    model = Stub(by_prompt())
    x = Contrast().batch(Ex(model), [group([False, True, True, True, True, True])], library())[0]
    assert model.calls == [] and x.extras[OPERATIONS] == [] and x.lessons == []


def test_contrast_without_label():
    """Без верного ответа в работу идёт любая группа, ответ и награды скрыты."""
    model = Stub(by_prompt())
    g = Group("q", [episode(k=k) for k in range(3)])
    Contrast().batch(Ex(model), [g], library())[0]
    assert "<Ground Truth>\n[REDACTED]" in model.calls[2]["user"] and "(Reward [REDACTED])" in model.calls[2]["user"]


def test_contrast_bad_update():
    """Сверка без JSON-списка — пустые операции."""
    model = Stub(by_prompt(ops='{"operation": "ADD"}'))
    x = Contrast().batch(Ex(model), [group([True, True, False])], library())[0]
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
    m.learn(Ex(model), [extraction([dict(operation="UPDATE", id="G1", content="B: b2.")]), extraction([])])
    table = model.calls[0]["user"]
    assert "Experience G1:\nContent: B: b.\nRelated Operations:" in table and "Experience G0:\nContent: A: a.\nNo related" in table
    assert [(r.id, r.text) for r in m.records()] == [("r4", "A: a2."), ("r2", "B: b."), ("r5", "D: d.")]
    assert EXPERIENCES.prompt(Ex(model), m, {}, 0).system.endswith("experiences:\n[G0]. A: a2.\n[G1]. B: b.\n[G2]. D: d.")


def test_plan_retries_and_no_ops():
    """Без операций план всё равно строится (как в апстриме); JSON не разобрался — до трёх попыток."""
    model = Stub(lambda call: "no json")
    m = library("A: a.")
    m.learn(Ex(model), [extraction([])])
    assert len(model.calls) == 3 and "No batch operations." in model.calls[0]["user"] and len(m) == 1


def test_attempts_and_batch():
    """В зачёт итоговый агент (T=0.3, top_p 0.95), группа из 5 при T=0.7 с тем же top_p; неполный батч отбрасывается."""
    model = Stub(lambda call: right(call) if call["temperature"] == 0.3 else by_prompt()(call))
    summary = run(TASK, tfgrpo, model, 2)
    solver = model.solver_calls()
    assert [(c["temperature"], c["top_p"]) for c in solver[:1 + GROUP]] == [(0.3, 0.95)] + [(0.7, 0.95)] * GROUP
    assert summary["correct"] == 2
    assert not any(c["user"].startswith("<Experiences and Proposed Operations>") for c in model.calls)
    assert render.experiences([]) == "None"
