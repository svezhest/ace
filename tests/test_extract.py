"""Извлечение ACE и память ACE: рефлектор стенда (метки и без), диагноз с раундами новой попытки,
куратор операциями, отсев, playbook по разделам; стык при абляции."""
import pytest
from stub import TASK, Stub, episode

from ace import prompts
from ace.extract import LABELS, Extraction, Labels
from ace.extract.ace import Diagnose, Diagnosis, Reflection, Reflector, Tag, reported, used_line
from ace.learner import swap
from ace.loop import Group
from ace.methods.ace import Curation, Op, Ops, Playbook, SectionedPlaybook, ace, curate_rewrite


class Ex:
    """Эксперимент-заглушка: модель, номер вопроса и новая попытка из заготовленных эпизодов."""
    task, i, total, training = TASK, 0, 4, True

    def __init__(self, model, retries=()):
        self.model, self.retries, self.notes = model, list(retries), []

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
    x = Reflector()(Ex(model), group(episode("3", ok=False, target="4")), playbook("a", "b"))
    assert x.lessons == ["Check units."] and x.scores == [0.0]
    assert x.extras == {LABELS: Labels(["r1"], ["r2"])}
    user = model.calls[0]["user"]
    assert "wrong, correct answer: 4" in user and "[r1] a\n[r2] b" in user


def test_reflector_free():
    model = Stub(lambda call: "free lesson")
    r = Reflector(free=True)
    x = r(Ex(model), group(episode("3", ok=True)), playbook())
    assert r.gives == frozenset() and x.lessons == ["free lesson"] and x.extras == {}
    assert prompts.text("reflect_free_form") in model.calls[0]["user"]


def test_ablation_needs_both_levels():
    """Рефлексия без меток при памяти со счётчиками и отсевом не собирается."""
    with pytest.raises(ValueError, match="labels"):
        swap(ace, extract=Reflector(free=True))
    swap(ace, extract=Reflector(free=True), memory=Playbook(prune=None))


def test_playbook_learn():
    """Метки -> журнал, уроки -> куратор (UPDATE — новый пункт), затем отсев вредных."""
    m = playbook("a", "b")
    m.count([], ["r2", "r2"])
    model = Stub(schemas={"Ops": Ops(ops=[Op(op="UPDATE", id="r1", text="a2"), Op(op="ADD", text="c")])})
    x = Extraction(group(episode()), ["lesson"], [1.0], {LABELS: Labels(["r1"], ["r2"])})
    m.learn(Ex(model), [x])
    assert [(r.id, r.text, r.helpful) for r in m.records()] == [("r3", "a2", 0), ("r4", "c", 0)]
    assert "- lesson" in model.calls[0]["user"] and "[r1] a" in model.calls[0]["user"]


def test_playbook_rewrite():
    m = Playbook(curate_rewrite)
    m.add("a")
    m.learn(Ex(Stub(lambda call: " first bullet \n\n second\n")), [Extraction(group(episode()), ["l"], [], {})])
    assert [(r.id, r.text) for r in m.records()] == [("r2", "first bullet"), ("r3", "second")]
    m = Playbook(curate_rewrite)
    m.learn(Ex(Stub(lambda call: "")), [Extraction(group(episode()), ["l"], [], {LABELS: Labels()})])
    assert m.records() == []


def test_used_line():
    assert used_line("x\nUSED: r1, [r2]\nFINAL ANSWER: 1") == ["r1", "r2"]
    assert used_line("USED: r1\nused: r3\n") == ["r3"]
    assert reported(episode(final="USED: r1, r9"), playbook("a")) == ["r1"]


def diagnosis(tags):
    return Diagnosis(reasoning="", error_identification="", root_cause_analysis="", correct_approach="",
                     key_insight="k", bullet_tags=[Tag(id=i, tag=t) for i, t in tags])


def test_diagnose_rounds():
    """Неверный ответ: диагноз, метки в копию памяти, новая попытка с диагнозом; до верной попытки."""
    tags = iter([[("r1", "harmful")], [("r1", "harmful"), ("r2", "helpful")], [("r2", "helpful")]])
    model = Stub(schemas={"Diagnosis": lambda call: diagnosis(next(tags))})
    memory = playbook("a", "b")
    retries = [episode("5", ok=False, target="4", final="USED: r1"), episode("4", ok=True, target="4")]
    ex = Ex(model, retries)
    x = Diagnose()(ex, group(episode("3", ok=False, target="4", final="USED: r1, r2")), memory)
    assert [n[1] for n in ex.notes] == [[(0, 1), (0, 0)], [(0, 2), (1, 0)]]     # метки раундов — в копию
    assert x.extras[LABELS] == Labels(["r2"], ["r1", "r1"])
    assert [r.harmful for r in memory.records()] == [0, 0]   # сама память не тронута
    assert x.lessons == [diagnosis([("r1", "harmful"), ("r2", "helpful")]).model_dump_json(indent=2)]
    assert ex.notes[0][0] == diagnosis([("r1", "harmful")]).model_dump_json(indent=2)
    users = [c["user"] for c in model.calls]
    assert "[r1] helpful=0 harmful=0 :: a\n[r2] helpful=0 harmful=0 :: b" in users[0]
    assert "[r1] helpful=0 harmful=1 :: a" in users[1] and "harmful=0 :: b" not in users[1]


def test_diagnose_right_answer_one_round():
    model = Stub(schemas={"Diagnosis": diagnosis([("r1", "helpful")])})
    ex = Ex(model)
    x = Diagnose()(ex, group(episode("4", ok=True, target="4", final="USED: r1")), playbook("a"))
    assert len(model.calls) == 1 and ex.notes == [] and x.extras[LABELS] == Labels(["r1"], [])


def test_diagnose_without_label():
    """Без верного ответа — промпт _nogt, без ground truth; раунд один, после него новая попытка, как в апстриме."""
    model = Stub(schemas={"Diagnosis": diagnosis([])})
    ex = Ex(model, [episode("5")])
    Diagnose()(ex, group(episode("4", ok=None)), playbook())
    assert len(ex.notes) == 1 and len(model.calls) == 1
    assert prompts.text("ace_no_bullets") in model.calls[0]["user"]
    assert model.calls[0]["user"] == prompts.load("ace_reflector_nogt").fill(
        question="q", reasoning_trace="FINAL ANSWER: 4", predicted_answer="4",
        environment_feedback=prompts.text("ace_environment_feedback", correct=None),
        bullets_used=prompts.text("ace_no_bullets"))


def test_sectioned_playbook():
    m = SectionedPlaybook()
    model = Stub(schemas={"Curation": Curation(reasoning="", operations=[
        dict(type="ADD", section="Formulas & Calculations", content="f"), dict(type="ADD", section="nowhere", content="o"),
        dict(type="UPDATE", section="others", content="skip")])})
    m.learn(Ex(model), [Extraction(group(episode(target="4")), ["{json}"], [], {LABELS: Labels()})])
    assert [(m.section_of(r.id), r.text) for r in m.records()] == [("formulas_and_calculations", "f"), ("others", "o")]
    user = model.calls[0]["user"]
    assert "## STRATEGIES & INSIGHTS\n\n## FORMULAS & CALCULATIONS" in user and "{json}" in user
    m.count(["r1"] * 6, [])
    assert m.stats()["high_performing"] == 1 and m.stats()["by_section"]["OTHERS"]["count"] == 1
