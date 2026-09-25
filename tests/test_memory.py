"""Память: правка текста — новая запись со статистикой с нуля, операции и права, журнал исходов, отсев,
разделы с общей нумерацией, документы."""
import dataclasses

import pytest

from ace.memory import Counted, Document, Files, Lesson, Lessons, Sections
from ace.memory.counters import count, prune_harmful


def three():
    m = Lessons("bullet", Counted)
    for t in ("a", "b", "c"):
        m.add(t)
    return m


def test_update_is_new_record():
    m = three()
    count(m, ["r2", "r2"], ["r2"])
    new = m.update("r2", "b2")
    assert [(r.id, r.text) for r in m.records()] == [("r1", "a"), ("r4", "b2"), ("r3", "c")]
    assert (new.helpful, new.harmful) == (0, 0)
    assert m.update("r9", "x") is None


def test_text_is_frozen():
    with pytest.raises(dataclasses.FrozenInstanceError):
        three().get("r1").text = "changed"


def test_count_and_prune():
    m = three()
    count(m, ["r1", "r9"], ["r2", "r2", "r2", "r3"])
    assert [(r.helpful, r.harmful) for r in m.records()] == [(1, 0), (0, 3), (0, 1)]
    prune_harmful(m, 3)
    assert [r.id for r in m.records()] == ["r1", "r3"]


def test_apply_ops():
    m = Lessons()
    m.add("a")
    m.apply([dict(operation="ADD", content="b"), dict(operation="UPDATE", id="r1", content="a2"),
             dict(operation="DELETE", id="r9", content="x"), dict(operation="NONE", content="y"),
             dict(operation="ADD", content=""), dict(operation="UPDATE", id="r9", content="z")])
    assert [(r.id, r.text) for r in m.records()] == [("r3", "a2"), ("r2", "b")]
    m.apply([dict(operation="UPDATE", id="r9", content="z")], missing="add")
    assert m.records()[-1].text == "z"
    full = Lessons()
    full.add("a")
    full.apply([dict(operation="DELETE", id="r1", content="x")])
    assert full.records() == []


def test_replace():
    m = three()
    count(m, ["r1"], [])
    m.replace(["whole"])
    assert [(r.id, r.text, r.helpful) for r in m.records()] == [("r4", "whole", 0)]


def test_dump_and_key():
    m = three()
    count(m, ["r1"], [])
    assert m.dump()[0] == dict(kind="bullet", id="r1", text="a", outcomes=["helpful"], helpful=1, harmful=0)
    assert m.key() == ("a", "b", "c") and m.chars() == 3


def test_sections():
    s = Sections(["one", "two"], "bullet", Counted)
    s.add("a", "two")
    s.add("b", "one")
    s.add("c", "two")
    assert [r.id for r in s.records()] == ["r1", "r2", "r3"]
    assert [r.id for r in s.sections["two"].records()] == ["r1", "r3"]
    count(s, ["r1"], [])
    s.update("r1", "a2")
    assert [(r.id, r.text) for r in s.sections["two"].records()] == [("r4", "a2"), ("r3", "c")]
    s.delete("r2")
    assert [d["section"] for d in s.dump()] == ["two", "two"]


def test_birth_fields():
    @dataclasses.dataclass(frozen=True, eq=False)
    class Rule(Lesson):
        confidence: float = 0.5
    m = Lessons(record=Rule)
    assert m.add("x", confidence=0.9).confidence == 0.9
    assert m.update("r1", "y").confidence == 0.5


def test_document():
    d = Document()
    assert d.records() == [] and d.dump() == []
    d.rewrite("sheet")
    assert d.records()[0].text == "sheet" and d.key() == "sheet"


def test_files():
    f = Files()
    f.write("a/b.md", "x\ny")
    f.write("c.md", "z")
    assert f.ls() == (["a"], [("c.md", "z")])
    assert f.ls("a") == ([], [("b.md", "x")])
    f.delete("a/b.md")
    assert f.ls() == ([], [("c.md", "z")])


def test_dedup_unparsed_merge_keeps_group(monkeypatch):
    """Ответ слияния не разобрался — группа похожих пунктов остаётся целиком, как у апстрима."""
    import numpy as np
    from stub import Stub

    from ace.memory import ace as A
    monkeypatch.setattr("ace.embed.embed", lambda texts: np.ones((len(texts), 4)) / 2.0)
    p = A.SectionedPlaybook(dedup=A.DEDUP)
    for t in ("rule a", "rule b", "rule c"):
        p.add(t, "formulas_and_calculations")

    class Ex:
        model = Stub(lambda call: "sorry, cannot merge")
    p.merge_similar(Ex())
    assert [r.text for r in p.records()] == ["rule a", "rule b", "rule c"]


def test_playbook_key_sees_counters():
    """Кэш val у playbook апстрима различает счётчики: решатель видит их в playbook."""
    from ace.memory.ace import SectionedPlaybook
    p = SectionedPlaybook()
    p.add("rule", "formulas_and_calculations")
    before = p.key()
    count(p, [p.records()[0].id], [])
    assert p.key() != before
