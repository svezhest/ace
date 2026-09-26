"""DC: генератор апстрима (вход задачи, cheatsheet в промпте, ответ <answer>, разговор с исполнением кода),
cheatsheet целиком (куратор переписывает, без блока остаётся старый), пары DC-RS и синтез под вопрос,
синтезированный cheatsheet сохраняется; контроли retrieval и history."""
import numpy as np
from stub import TASK, Stub, episode, experiment

from ace import prompts
from ace.extract import INPUT, SHEET, Seen
from ace.loop import Group, run
from ace.memory.dc import Cheatsheet, Pairs
from ace.methods.dc import dc, dc_code, dc_history, dc_retrieval, dc_rs
from ace.parse import dc_answer
from ace.render import EMPTY
from ace.solver import dc as show
from ace.tasks import TASKS

ITEM = {"question": "What is 2 / 4?", "target": "0.5"}


def extraction(ep):
    return Seen()(experiment(), Group(ep.question, [ep]), None)


def generated(prompt, question="q1"):
    """Эпизод с промптом генератора (куратору нужен вход задачи)."""
    ep = episode(question=question)
    ep.prompt = prompt
    return ep


def test_input():
    assert show.dc_input("formula", 0, "x") == "Question #1:\nx"
    meb = show.dc_input("meb", 4, "1 ? 2 = 3")
    assert meb.startswith("Below is an equation") and meb.endswith("= 6.\n\nEquation: Question #5:\n1 ? 2 = 3")


def test_answer():
    assert dc_answer("a <answer>1</answer> b <answer> 2 + 3 = 5 </answer>") == "2 + 3 = 5"
    assert dc_answer("FINAL ANSWER:\n```\n1 + 2 = 3\n```") == "1 + 2 = 3"
    assert dc_answer("FINAL ANSWER: 3") == dc_answer("nothing") == "No final answer found"


def test_generator_prompt():
    p = dc.solver.prompt(experiment(), Cheatsheet(), ITEM, 0)
    call = p.solver.call("")
    assert call.params == {"temperature": 0.0, "max_completion_tokens": 2048}
    assert [m["role"] for m in call.messages] == ["user"]
    assert call.messages[0]["content"] == prompts.load("dc_generator").fill(QUESTION=p.seen[INPUT], CHEATSHEET=EMPTY)
    assert p.seen[INPUT] == "Question #1:\n" + ITEM["question"] and p.seen[SHEET] == EMPTY


def test_cheatsheet_rewrite():
    m = Cheatsheet()
    model = Stub(lambda call: "notes <cheatsheet>\nv1\n</cheatsheet>")
    p = dc.solver.prompt(experiment(), m, ITEM, 0)
    m.learn(experiment(model), [extraction(generated(p))])
    assert m.text == "v1" and dc.solver.prompt(experiment(), m, ITEM, 0).seen[SHEET] == "v1"
    call = model.calls[0]
    assert call["system"] == "" and p.seen[INPUT] in call["user"] and "FINAL ANSWER: 1" in call["user"] and EMPTY in call["user"]
    m.learn(experiment(Stub(lambda call: "no block")), [extraction(generated(p))])
    assert m.text == "v1"
    m.learn(experiment(Stub(lambda call: "<cheatsheet></cheatsheet>")), [extraction(generated(p))])
    assert m.text == "" and dc.solver.prompt(experiment(), m, ITEM, 0).seen[SHEET] == ""


def test_curator_params():
    seen = []

    class Params(Stub):
        def ask(self, call):
            seen.append(call.params)
            return super().ask(call)
    p = dc.solver.prompt(experiment(), Cheatsheet(), ITEM, 0)
    Cheatsheet().learn(experiment(Params(lambda call: "<cheatsheet>v</cheatsheet>")), [extraction(generated(p))])
    assert seen == [{"temperature": 0.0, "max_completion_tokens": 4096}]


def fake_embed(monkeypatch):
    vecs = {"q1": [0, 1], "q2": [1, 0], "q3": [0.8, 0.6], ITEM["question"]: [1, 0]}
    monkeypatch.setattr("ace.embed.embed", lambda texts: np.array([vecs[t] for t in texts], dtype=float))


def pairs(*questions, sheet=False):
    m = Pairs(sheet)
    for q in questions:
        m.add(f"solution of {q}", question=q)
    return m


def test_retrieval_and_history(monkeypatch):
    fake_embed(monkeypatch)
    assert dc_retrieval.solver.prompt(experiment(), pairs(), ITEM, 0).seen[SHEET] == EMPTY
    p = dc_retrieval.solver.prompt(experiment(), pairs("q1", "q2", "q3"), ITEM, 0)
    assert p.shown == ["r2", "r3", "r1"]
    text = p.seen[SHEET]
    assert prompts.text("dc_note") in text and "(Similarity: 1.00)" in text
    assert text.index("solution of q2") > text.index("solution of q3") > text.index("solution of q1")     # самая похожая последней
    h = dc_history.solver.prompt(experiment(), pairs("q1", "q2"), ITEM, 0).seen[SHEET]
    assert h.index("q1") < h.index("q2") and "Similarity" not in h


def test_upstream_embeddings():
    """Вопросы meb с готовыми эмбеддингами апстрима: близость по ним, BGE-M3 не нужна."""
    qs = [r["question"] for r in TASKS["meb"].load()[:4]]
    p = dc_retrieval.solver.prompt(experiment(), pairs(*qs[:3]), {"question": qs[3]}, 0)
    assert len(p.shown) == 3 and "(Similarity: 0." in p.seen[SHEET]


def test_synthesis_kept(monkeypatch):
    """Синтез видит пары, вход задачи и прошлый cheatsheet; синтезированный текст — в промпте генератора, память
    его хранит."""
    fake_embed(monkeypatch)
    m = pairs("q1", sheet=True)
    model = Stub(lambda call: "<cheatsheet>for this question</cheatsheet>")
    p = dc_rs.solver.prompt(experiment(model), m, ITEM, 0)
    assert p.seen[SHEET] == "for this question" and "for this question" in p.solver.call("").messages[0]["content"]
    user = model.calls[0]["user"]
    assert "solution of q1" in user and p.seen[INPUT] in user and EMPTY in user
    m.learn(experiment(model), [extraction(generated(p, ITEM["question"]))])
    assert [r.question for r in m.records()] == ["q1", ITEM["question"]] and m.sheet.text == "for this question"
    assert [d["kind"] for d in m.dump()] == ["pair", "pair", "sheet"]


def test_synthesis_fallback():
    """Без блока <cheatsheet> генератор видит сами пары, и они же сохраняются как cheatsheet (как в апстриме)."""
    p = dc_rs.solver.prompt(experiment(Stub(lambda call: "nothing")), Pairs(sheet=True), ITEM, 0)
    assert p.seen[SHEET] == EMPTY


def test_dc_run():
    """Цикл: без вердикта, куратор после каждого вопроса, генератор видит новый cheatsheet и номер вопроса."""
    model = Stub(lambda call: "<cheatsheet>v</cheatsheet>" if "CHEATSHEET" in call["user"] else "<answer>1</answer>")
    run(TASK, dc, model, 2)
    assert len(model.calls) == 4 and "Question #2:" in model.calls[2]["user"] and "\nv\n" in model.calls[2]["user"]


def test_code_rounds(monkeypatch):
    """Разговор с кодом: вывод песочницы в формате апстрима, просьба продолжить, в последнем раунде —
    предупреждение; после трёх продолжений последний блок дописывается ещё раз. Без кода — один вызов."""
    ran = []

    def fake_run(code, container=None, limit=10, path=None):
        ran.append((code, limit, path))
        return {"stdout": "4\n", "stderr": "", "rc": 0, "timeout": False}
    monkeypatch.setattr("ace.env.sandbox.run", fake_run)
    block = "```python\nx = 2\nx * 2\n```\nEXECUTE CODE! trailing"
    model = Stub(lambda call: block)
    p = dc_code.solver.prompt(experiment(), Cheatsheet(), ITEM, 0)
    reply = p.solver.talk(model, p.solver.call(""))
    assert ran[0] == ("x = 2\nprint(x * 2)", 3, "/tmp/code.py") and len(model.calls) == 4
    current = "```python\nx = 2\nx * 2\n```\nEXECUTE CODE!\n\nOutput of the Python code above:\n```\n4\n```"
    assert reply.text == "\n\n".join([current] * 5)
    assert model.calls[1]["user"] == prompts.text("dc_proceed")
    assert model.calls[3]["user"] == prompts.text("dc_proceed") + prompts.text("dc_last_round")
    plain = dc.solver.prompt(experiment(), Cheatsheet(), ITEM, 0)
    assert plain.solver.talk(Stub(lambda call: block), plain.solver.call("")).text == block


def test_code_output(monkeypatch):
    """execute_code_with_timeout: без stdout — stderr, без обоих — просьба напечатать, предел — сообщение апстрима."""
    outs = iter([{"stdout": "", "stderr": "Traceback\nNameError", "rc": 1, "timeout": False},
                 {"stdout": "", "stderr": "", "rc": 0, "timeout": False},
                 {"stdout": "", "stderr": "", "rc": 124, "timeout": True}])
    monkeypatch.setattr("ace.env.sandbox.run", lambda code, **kw: next(outs))
    assert "Error in execution: Traceback\nNameError" in show.run_block("```python\nprint(y)\n```")
    assert "No output was generated" in show.run_block("```python\n# nothing\n```")
    assert "Execution took too long, aborting..." in show.run_block("```python\nwhile True: pass\n```")
    assert show.run_block("no code") == ""
    assert show.run_block("```python\n```") == "PYTHON CODE OUTPUT:\n```\nError: list index out of range\n```"
