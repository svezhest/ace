"""SCOPE: правило на шаг (ошибка и качество, Best-of-N с селектором, классификатор), память перспективы
(допуск, предел 20 за прогон, tactical на попытку, strategic при 0.85, дубль по словам, предел домена с
оптимизатором), Patch системного промпта на шаге, перспективы K=2 с зачётом pass@k."""
from stub import TASK, Stub, episode, right

from ace.extract import CONFIDENCE, DOMAIN, RATIONALE, Extraction
from ace.extract.scope import Classification, Proposal, Rules, Selection, answer_step, tool_step
from ace.learner import swap
from ace.loop import Attempt, Group, Prompt, run
from ace.methods.scope import (CAP, PER_RUN, TARGET, Analysis, Book, Perspectives, Rule, Strategic, compress,
                               duplicate_words, scope, scope_k2)
from ace.model import Patch, Step


class Ex:
    task, training = TASK, True

    def __init__(self, model):
        self.model = model


def rule(text, confidence=0.9, domain="general", rationale="why"):
    return Extraction(None, [text], [], {CONFIDENCE: [confidence], DOMAIN: [domain], RATIONALE: [rationale]})


def attempt(system="SYS", shown=""):
    return Attempt("q", 0, True, Prompt(shown), system)


ERROR = Step("run_python", '{"code": "1/0"}', "Traceback ...\nZeroDivisionError: division by zero")
FINE = Step("run_python", '{"code": "1"}', "1")


def test_steps():
    summary, error = tool_step(ERROR)
    assert summary.startswith("Tool calls: run_python") and error[0] == "ToolError"
    assert tool_step(FINE)[1] is None
    assert answer_step(episode("3", ok=False, target="4"))[1][1] == "Incorrect answer. Model answered '3', expected '4'."
    assert answer_step(episode("3", ok=True))[1] is None


def test_propose_error_and_quality():
    model = Stub(schemas={"Proposal": Proposal(update_text="Check the denominator.", confidence="high")})
    book = Book()
    assert Rules().propose(Ex(model), attempt(), book, *tool_step(ERROR)).update_text == "Check the denominator."
    assert "analyzing agent execution errors" in model.calls[0]["user"] and "ZeroDivisionError" in model.calls[0]["user"]
    model.schemas["Proposal"] = Proposal(update_text="No improvement needed")
    assert Rules().propose(Ex(model), attempt(), book, *tool_step(FINE)) is None
    assert "**Correctness & Logic**" in model.calls[1]["user"]          # перспектива по умолчанию — thoroughness
    # с ошибкой «none» не отбрасывается, как в апстриме
    model.schemas["Proposal"] = Proposal(update_text="none")
    assert Rules().propose(Ex(model), attempt(), book, *tool_step(ERROR)).update_text == "none"


def test_best_of_two():
    texts = iter(["first", "second"])
    model = Stub(schemas={"Proposal": lambda call: Proposal(update_text=next(texts)), "Selection": Selection(selected_index=1)})
    p = Rules(n=2).propose(Ex(model), attempt(), Book(), *tool_step(FINE))
    assert p.update_text == "second"
    assert [c["temperature"] for c in model.calls] == [0.7, 0.7, 0]
    assert "[Candidate 0]\nUpdate: first" in model.calls[2]["user"]


def test_classify():
    model = Stub(schemas={"Classification": Classification(scope="strategic", confidence=0.95, domain="made_up")})
    x = Rules().classify(Ex(model), Proposal(update_text="Always check units.", rationale="r", confidence="low"), Book())
    assert x.lessons == ["Always check units."] and x.extras == {CONFIDENCE: [0.95], DOMAIN: ["general"], RATIONALE: ["r"]}
    assert "Initial Confidence: 0.30" in model.calls[0]["user"]
    model.schemas["Classification"] = Classification(scope="tactical", confidence=None)
    assert Rules().classify(Ex(model), Proposal(update_text="x", confidence="high"), Book()).extras[DOMAIN] == [None]
    assert Rules().classify(Ex(model), Proposal(update_text="x", confidence="high"), Book()).extras[CONFIDENCE] == [0.9]
    model.schemas["Classification"] = Classification(is_duplicate=True)
    assert Rules().classify(Ex(model), Proposal(update_text="x"), Book()) is None
    model.schemas["Classification"] = None           # сбой классификатора: tactical с исходной confidence
    assert Rules().classify(Ex(model), Proposal(update_text="x", confidence="medium"), Book()).extras[DOMAIN] == [None]


def test_admission_and_promotion():
    book, ex = Book(), Ex(Stub())
    book.learn(ex, [rule("low", 0.4), rule("tactical only", 0.6, None), rule("mid", 0.8), rule("Always check units.", 0.9)])
    assert [r.text for r in book.tactical] == ["tactical only", "mid", "Always check units."]
    assert [r.text for r in book.records()] == ["Always check units."]
    book.learn(ex, [rule("always check units", 0.95), rule("Round at the end.", 0.99, "efficiency")])
    assert [r.text for r in book.records()] == ["Always check units.", "Round at the end."]     # дубль по словам не прошёл
    assert list(book.domains) == ["general", "efficiency"]
    book.begin()
    assert book.tactical == [] and book.accepted == 5


def test_limit_per_run_is_not_reset():
    book, ex = Book(), Ex(Stub())
    for i in range(PER_RUN + 3):
        book.begin()
        book.learn(ex, [rule(f"rule number {i} " + "x" * i, 0.6, None)])
    assert book.accepted == PER_RUN


def test_domain_cap_optimizer():
    analysis = Analysis(consolidation=[[0, 1, 2, 3]])
    model = Stub(schemas={"Analysis": analysis, "Rule": Rule(rule="merged", rationale="m")})
    book, ex = Book(), Ex(model)
    for i in range(CAP + 1):
        book.learn(ex, [rule(" ".join(f"w{i}{j}" for j in range(5)), 0.86 + i / 1000)])
    texts = [r.text for r in book.records()]
    assert len(texts) == TARGET and texts[-1] == "merged"
    assert [c["output"].__name__ for c in model.calls] == ["Analysis", "Rule"]          # после слияния 8 правил: второго прохода нет
    # нетронутая запись осталась собой
    assert all(isinstance(r, Strategic) for r in book.records())


def test_compress_keeps_untouched():
    recs = [Strategic(f"r{i}", f"t{i}") for i in range(4)]
    out = compress(None, recs, lambda model, rules, target: rules[1:] + [dict(rule="new", rationale="", confidence=0.9)],
                   2, 3, lambda x: Strategic("n", x["rule"]))
    assert out[:2] == recs[1:3] and len(out) == 3


def test_duplicate_words():
    assert duplicate_words("check units", ["Always check units first"])
    assert duplicate_words("a b c d e f g h i j", ["a b c d e f g h x y"])
    assert not duplicate_words("a b c d e f g x y z", ["a b c d e f g h i j"])


def test_step_patch_rewrites_system():
    model = Stub(schemas={"Proposal": Proposal(update_text="Guard division.", confidence="high"),
                          "Classification": Classification(scope="strategic", confidence=0.9)})
    memory = Perspectives()
    s = swap(scope, memory=memory)
    a = attempt()
    patch = s.on_step(Ex(model), a, ERROR)
    assert patch == Patch(system="SYS\n\n## Learned Guideline:\nGuard division.")
    model.schemas["Proposal"] = Proposal(update_text="Print intermediate values.", confidence="high")
    patch = s.on_step(Ex(model), a, FINE)
    assert patch.system == "SYS\n\n## Learned Guideline:\nGuard division.\n\n## Learned Guideline:\nPrint intermediate values."
    assert [r.text for r in memory.book(0).records()] == ["Guard division.", "Print intermediate values."]
    a.training = False
    assert s.on_step(Ex(model), a, ERROR) is None
    # новая попытка: tactical прошлой ушли, strategic показаны при запуске
    p = s.prompt(Ex(model), {"context": "q"}, 0)
    assert memory.book(0).tactical == []
    assert p.system.startswith("\n## Strategic Guidelines") and "### General:\n- Guard division." in p.system


def test_k2_own_memory_per_perspective():
    model = Stub(lambda call: right(call) if "## Strategic" not in call["system"] else "FINAL ANSWER: 0",
                 schemas={"Proposal": Proposal(update_text="u", confidence="high"),
                          "Classification": Classification(scope="strategic", confidence=0.9)})
    run(TASK, scope_k2, model, 1)
    proposals = [c for c in model.calls if c["output"] is Proposal]
    assert len(proposals) == 2
    # в зачёт первая попытка (efficiency), она и учится первой; вторая — thoroughness
    assert "**Correctness & Logic**" not in proposals[0]["user"] and "**Correctness & Logic**" in proposals[1]["user"]


def test_answer_order_chosen_first():
    model = Stub(schemas={"Proposal": lambda call: Proposal(update_text=f"u{len(model.calls)}"),
                          "Classification": Classification(scope="tactical", confidence=0.9)})
    memory = Perspectives(("efficiency", "thoroughness"))
    g = Group("q", [episode("1", ok=False, k=0), episode("2", ok=True, k=1)], chosen=1)
    out = Rules().answers(Ex(model), g, memory)
    assert [k for k, _ in out] == [1, 0]
    assert [c["output"].__name__ for c in model.calls] == ["Proposal", "Proposal", "Classification", "Classification"]
