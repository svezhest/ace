"""DC: cheatsheet целиком (куратор переписывает, без блока остаётся старый), пары DC-RS и синтез под вопрос,
синтезированный cheatsheet сохраняется; контроли retrieval и history."""
import numpy as np
from stub import TASK, Stub, episode

from ace import prompts
from ace.extract import Raw
from ace.loop import Group, run
from ace.memory.dc import Cheatsheet, Pairs
from ace.methods.dc import dc, dc_history, dc_retrieval, dc_rs
from ace.render import EMPTY
from ace.show.dc import SheetPrompt
from ace.show import HEAD

ITEM = {"context": "What is 2 / 4?", "target": "0.5"}


class Ex:
    task, training = TASK, True

    def __init__(self, model):
        self.model = model


def extraction(ep):
    return Raw()(Ex(None), Group(ep.question, [ep]), None)


def test_cheatsheet_rewrite():
    m = Cheatsheet()
    assert m.records() == [] and dc.show.prompt(Ex(None), m, ITEM, 0).system == "\n\n" + HEAD + EMPTY
    model = Stub(lambda call: "notes <cheatsheet>\nv1\n</cheatsheet>")
    m.learn(Ex(model), [extraction(episode(question="q1"))])
    assert m.text == "v1"
    call = model.calls[0]
    assert call["system"] == "" and "q1" in call["user"] and "FINAL ANSWER: 1" in call["user"] and EMPTY in call["user"]
    m.learn(Ex(Stub(lambda call: "no block")), [extraction(episode())])
    assert m.text == "v1"
    m.learn(Ex(Stub(lambda call: "<cheatsheet></cheatsheet>")), [extraction(episode())])
    assert m.text == "" and dc.show.prompt(Ex(None), m, ITEM, 0).system == ""


def test_curator_budget():
    seen = []

    class Budget(Stub):
        def run(self, *args, max_tokens=None, **kw):
            seen.append(max_tokens)
            return super().run(*args, max_tokens=max_tokens, **kw)
    model = Budget(lambda call: "<cheatsheet>v</cheatsheet>")
    Cheatsheet().learn(Ex(model), [extraction(episode())])
    assert seen == [2 * model.max_tokens]


def fake_embed(monkeypatch):
    vecs = {"q1": [0, 1], "q2": [1, 0], "q3": [0.8, 0.6], ITEM["context"]: [1, 0]}
    monkeypatch.setattr("ace.embed.embed", lambda texts: np.array([vecs[t] for t in texts], dtype=float))


def pairs(*questions, sheet=False):
    m = Pairs(sheet)
    for q in questions:
        m.add(f"solution of {q}", question=q)
    return m


def test_retrieval_and_history(monkeypatch):
    fake_embed(monkeypatch)
    assert dc_retrieval.show.prompt(Ex(None), pairs(), ITEM, 0).system == "\n\n" + HEAD + EMPTY
    p = dc_retrieval.show.prompt(Ex(None), pairs("q1", "q2", "q3"), ITEM, 0)
    assert p.shown == ["r2", "r3", "r1"]
    text = p.system
    assert prompts.text("dc_note") in text and "(Similarity: 1.00)" in text
    assert text.index("solution of q2") > text.index("solution of q3") > text.index("solution of q1")     # самая похожая последней
    h = dc_history.show.prompt(Ex(None), pairs("q1", "q2"), ITEM, 0).system
    assert h.index("q1") < h.index("q2") and "Similarity" not in h


def test_synthesis_kept(monkeypatch):
    """Синтез видит пары, вопрос и прошлый cheatsheet; синтезированный текст в промпте попытки, память его хранит."""
    fake_embed(monkeypatch)
    m = pairs("q1", sheet=True)
    model = Stub(lambda call: "<cheatsheet>for this question</cheatsheet>")
    p = dc_rs.show.prompt(Ex(model), m, ITEM, 0)
    assert isinstance(p, SheetPrompt) and p.sheet == "for this question" and p.system.endswith("for this question")
    user = model.calls[0]["user"]
    assert "solution of q1" in user and ITEM["context"] in user and EMPTY in user
    ep = episode(question=ITEM["context"])
    ep.prompt = p
    m.learn(Ex(model), [extraction(ep)])
    assert [r.question for r in m.records()] == ["q1", ITEM["context"]] and m.sheet.text == "for this question"
    assert [d["kind"] for d in m.dump()] == ["pair", "pair", "sheet"]


def test_synthesis_fallback():
    """Без блока <cheatsheet> решатель видит сами пары, и они же сохраняются как cheatsheet (как в апстриме)."""
    m = Pairs(sheet=True)
    p = dc_rs.show.prompt(Ex(Stub(lambda call: "nothing")), m, ITEM, 0)
    assert p.sheet == EMPTY and p.system == "\n\n" + HEAD + EMPTY


def test_dc_run():
    """Цикл: без вердикта, куратор после каждого вопроса."""
    model = Stub(lambda call: "<cheatsheet>v</cheatsheet>" if "CHEATSHEET" in call["user"] else "FINAL ANSWER: 1")
    run(TASK, dc, model, 2)
    assert len(model.calls) == 4 and "\n\n" + HEAD + "v" in model.calls[2]["system"]
