"""Извлечение ACE и память ACE: рефлектор стенда (метки и без), диагноз с раундами новой попытки,
куратор операциями, отсев, playbook по разделам; стык при абляции."""
import json

import pytest
from stub import TASK, Stub, episode, experiment

from ace import prompts
from ace.extract import LABELS, Extraction, Labels
from ace.extract.ace import Diagnose, Reflection, Reflector, named, used_line
from ace.learner import swap
from ace.loop import Experiment, Group
from ace.memory.counters import count
from ace.memory.ace import Op, Ops, Playbook, SectionedPlaybook, curate_rewrite
from ace.methods.ace import ace_stand


class Retrying(Experiment):
    """Эксперимент, у которого новая попытка — из заготовленных эпизодов; заметка и метки памяти раунда — в notes."""
    def __init__(self, model, retries=()):
        super().__init__(TASK, None, model)
        self.retries, self.notes = list(retries), []

    def retry(self, memory, note):
        self.notes.append((note, [(r.helpful, r.harmful) for r in memory.records()]))
        return self.retries.pop(0)


def group(*eps):
    return Group(eps[0].question, list(eps), target=eps[0].target)


def playbook(*texts):
    m = Playbook()
    for t in texts:
        m.add(t)
    return m


def test_reflector_labels():
    model = Stub(schemas={"Reflection": Reflection(lessons=["Check units."], helpful=["r1"], harmful=["r2"])})
    x = Reflector()(experiment(model), group(episode("3", ok=False, target="4")), playbook("a", "b"))
    assert x.lessons == ["Check units."] and x.scores == [0.0]
    assert x.extras == {LABELS: Labels(["r1"], ["r2"])}
    user = model.calls[0]["user"]
    assert "wrong, correct answer: 4" in user and "[r1] a\n[r2] b" in user


def test_reflector_free():
    model = Stub(lambda call: "free lesson")
    r = Reflector(free=True)
    x = r(experiment(model), group(episode("3", ok=True)), playbook())
    assert r.gives == frozenset() and x.lessons == ["free lesson"] and x.extras == {}
    assert prompts.text("reflect_free_form") in model.calls[0]["user"]


def test_ablation_needs_both_levels():
    """Рефлексия без меток при памяти со счётчиками и отсевом не собирается."""
    with pytest.raises(ValueError, match="labels"):
        swap(ace_stand, extract=Reflector(free=True))
    swap(ace_stand, extract=Reflector(free=True), memory=Playbook(prune=None))


def test_playbook_learn():
    """Метки -> журнал, уроки -> куратор (UPDATE — новый пункт), затем отсев вредных."""
    m = playbook("a", "b")
    count(m, [], ["r2", "r2"])
    model = Stub(schemas={"Ops": Ops(ops=[Op(op="UPDATE", id="r1", text="a2"), Op(op="ADD", text="c")])})
    x = Extraction(group(episode()), ["lesson"], [1.0], {LABELS: Labels(["r1"], ["r2"])})
    m.learn(experiment(model), [x])
    assert [(r.id, r.text, r.helpful) for r in m.records()] == [("r3", "a2", 0), ("r4", "c", 0)]
    assert "- lesson" in model.calls[0]["user"] and "[r1] a" in model.calls[0]["user"]


def test_playbook_rewrite():
    m = Playbook(curate_rewrite)
    m.add("a")
    m.learn(experiment(Stub(lambda call: " first bullet \n\n second\n")), [Extraction(group(episode()), ["l"], [], {})])
    assert [(r.id, r.text) for r in m.records()] == [("r2", "first bullet"), ("r3", "second")]
    m = Playbook(curate_rewrite)
    m.learn(experiment(Stub(lambda call: "")), [Extraction(group(episode()), ["l"], [], {LABELS: Labels()})])
    assert m.records() == []


def test_used_line():
    assert used_line("x\nUSED: r1, [r2]\nFINAL ANSWER: 1") == ["r1", "r2"]
    assert used_line("USED: r1\nused: r3\n") == ["r3"]


def diagnosis(tags):
    """Ответ рефлектора текстом, как у апстрима: JSON с bullet_tags."""
    return json.dumps(dict(reasoning="", key_insight="k", bullet_tags=[dict(id=i, tag=t) for i, t in tags]))


def test_diagnose_rounds():
    """Неверный ответ: диагноз, метки в копию памяти, новая попытка с диагнозом; до верной попытки."""
    tags = [[("r1", "harmful")], [("r1", "harmful"), ("r2", "helpful")], [("r2", "helpful")]]
    replies = iter(diagnosis(t) for t in tags)
    model = Stub(lambda call: next(replies))
    memory = playbook("a", "b")
    retries = [episode("5", ok=False, target="4", final="USED: r1"), episode("4", ok=True, target="4")]
    ex = Retrying(model, retries)
    x = Diagnose(ids=named)(ex, group(episode("3", ok=False, target="4", final="USED: r2, r1")), memory)
    assert [n[1] for n in ex.notes] == [[(0, 1), (0, 0)], [(0, 2), (1, 0)]]     # метки раундов — в копию
    assert x.extras[LABELS] == Labels(["r2"], ["r1", "r1"])
    assert [r.harmful for r in memory.records()] == [0, 0]   # сама память не тронута
    assert x.lessons == [diagnosis(tags[1])] and ex.notes[0][0] == diagnosis(tags[0])
    users = [c["user"] for c in model.calls]
    assert "[r1] helpful=0 harmful=0 :: a\n[r2] helpful=0 harmful=0 :: b" in users[0]     # в порядке памяти
    assert "[r1] helpful=0 harmful=1 :: a" in users[1] and "harmful=0 :: b" not in users[1]


def test_diagnose_tags_as_upstream():
    """update_bullet_counts: повтор id — последняя метка, ключ bullet вместо id, neutral и чужие метки не считаются."""
    reply = ('text "bullet_tags": [{"id": "r1", "tag": "helpful"}, {"id": "r1", "tag": "harmful"}, '
             '{"bullet": "r2", "tag": "helpful"}, {"id": "r3", "tag": "useful"}] tail')
    x = Diagnose()(experiment(Stub(lambda call: reply)), group(episode("4", ok=True, target="4")), playbook("a", "b", "c"))
    assert x.extras[LABELS] == Labels(["r2"], ["r1"]) and x.lessons == [reply]


def test_diagnose_bullets_used():
    """ace_used: нет строки USED или none — «No bullets used»; названы, но нет в памяти — строка апстрима."""
    for final, text in (("FINAL ANSWER: 4", "ace_no_bullets"), ("USED: none", "ace_no_bullets"),
                        ("USED: r9", "ace_bullets_not_found")):
        model = Stub(lambda call: "")
        Diagnose(ids=named)(experiment(model), group(episode("4", ok=True, target="4", final=final)), playbook("a"))
        assert prompts.text(text) in model.calls[0]["user"]


def test_diagnose_right_answer_one_round():
    model = Stub(lambda call: diagnosis([("r1", "helpful")]))
    ex = Retrying(model)
    x = Diagnose()(ex, group(episode("4", ok=True, target="4", final="USED: r1")), playbook("a"))
    assert len(model.calls) == 1 and ex.notes == [] and x.extras[LABELS] == Labels(["r1"], [])


def test_diagnose_without_label():
    """Без верного ответа — промпт _nogt, без ground truth; раунд один, после него новая попытка, как в апстриме."""
    model = Stub(lambda call: diagnosis([]))
    ex = Retrying(model, [episode("5")])
    Diagnose()(ex, group(episode("4", ok=None)), playbook())
    assert len(ex.notes) == 1 and len(model.calls) == 1
    assert model.calls[0]["user"] == prompts.load("ace_reflector_nogt").fill(
        question="q", reasoning_trace="FINAL ANSWER: 4", predicted_answer="4",
        environment_feedback=prompts.text("ace_environment_feedback", correct=None),
        bullets_used=prompts.text("ace_no_bullets"))


def test_sectioned_playbook():
    """Куратор апстрима: только ADD, неизвестный раздел — OTHERS, id со слагом раздела и общим номером."""
    m = SectionedPlaybook()
    reply = json.dumps(dict(reasoning="", operations=[
        dict(type="ADD", section="Formulas & Calculations", content="f"), dict(type="ADD", section="nowhere", content="o"),
        dict(type="UPDATE", section="others", content="skip")]))
    model = Stub(lambda call: reply)
    m.learn(experiment(model), [Extraction(group(episode(target="4")), ["{json}"], [], {LABELS: Labels()})])
    assert [(m.section_of(r.id), r.id, r.text) for r in m.records()] == [
        ("formulas_and_calculations", "calc-00001", "f"), ("others", "misc-00002", "o")]
    user = model.calls[0]["user"]
    assert "## STRATEGIES & INSIGHTS\n\n## FORMULAS & CALCULATIONS" in user and "{json}" in user
    count(m, ["misc-00002"] * 6, [])
    assert m.stats()["high_performing"] == 1 and m.stats()["by_section"]["OTHERS"]["count"] == 1
