"""Обёртки: Gate (правка остаётся, если на val не хуже; решения в логе), Meta (навык перед первой попыткой прохода,
train за проход, откат к лучшей по val, при равенстве первая, без нулевой итерации), swap над обёрткой,
базовый агент MCE (context/ на запись, итоги только текущего батча в data/ на чтение), навык в промптах ACE."""
import copy
import json

from stub import TASK, Stub, episode, right

from ace import fs
from ace.extract import Raw
from ace.extract.ace import Reflection
from ace.learner import Learner, swap
from ace.loop import Group, run
from ace.memory import Lessons
from ace.methods.ace import Ops
from ace.methods.mce import Context, mce, mce_ace
from ace.wrap import Gate, Meta, Wrapper, skilled


class Source(list):
    """Тексты для Notes: общие для всех копий памяти (откат не возвращает взятые)."""
    def __deepcopy__(self, memo):
        return self


class Notes(Lessons):
    """На каждом батче добавляет следующий текст из списка."""
    requires = frozenset()

    def __init__(self, texts):
        super().__init__()
        self.texts = Source(texts)

    def learn(self, ex, extractions):
        if self.texts:
            self.add(self.texts.pop(0))


def good_only(call):
    """Верно, пока в показанной памяти есть good и нет bad."""
    return right(call) if "good" in call["system"] and "bad" not in call["system"] else "FINAL ANSWER: 0"


def notes(*texts, **levels):
    return Learner("notes", memory=Notes(texts), extract=Raw(), **levels)


def test_gate(tmp_path):
    model = Stub(good_only)
    run(TASK, Gate(notes("good", "bad", "good too")), model, 3, out=str(tmp_path))
    log = json.load(open(tmp_path / "log.json"))
    assert [r["gated"] for r in log] == [[True], [False], [True]]
    assert [r["text"] for r in json.load(open(tmp_path / "memory.json"))] == ["good", "good too"]


def test_gate_skips_unchanged():
    model = Stub(good_only)
    learner = Gate(notes())
    run(TASK, learner, model, 2)
    assert len(model.solver_calls()) == 2          # val не звали: память не менялась


def test_meta(tmp_path):
    seen = []

    def author(ex, history):
        seen.append([(h.text, h.train, h.val) for h in history])
        return f"skill {len(history)}"
    model = Stub(good_only)
    meta = Meta(notes("good", "x", "bad", "y", every=2, flush=True, epochs=2), author, "meta")
    run(TASK, meta, model, 3, out=str(tmp_path))
    # навык пишется раз за проход, по истории прошлых итераций; нулевой итерации нет
    assert seen == [[], [("skill 0", 1 / 3, 1.0)]]
    dump = json.load(open(tmp_path / "memory.json"))
    iterations = [r for r in dump if r["kind"] == "iterations"]
    # второй проход: память ухудшилась (bad), val 0 — откат к первой итерации
    assert [(r["text"], r["val"]) for r in iterations] == [("skill 0", 1.0), ("skill 1", 0.0)]
    assert iterations[1]["train"] == 2 / 3
    assert [r["text"] for r in dump if r["kind"] != "iterations"] == ["good", "x"]


def test_meta_tie_keeps_first():
    model = Stub(good_only)
    meta = Meta(notes("good", "x", "good 2", "y", every=3, flush=True, epochs=2), lambda ex, h: "s", "meta")
    ex_learner = []

    class Spy(Meta):
        def on_pass(self, ex):
            super().on_pass(ex)
            ex_learner.append([r.text for r in self.inner.memory.records()])
    spy = Spy(meta.inner, meta.author, "meta")
    run(TASK, spy, model, 3, epochs=2)
    assert ex_learner == [["good"], ["good"]]       # у второй итерации тот же val — следующая начнётся с первой


def test_swap_wrapper():
    w = swap(mce, "mce2", every=2)
    assert isinstance(w, Meta) and w.name == "mce2" and w.every == 2 and mce.every == 20
    assert w.inner is not mce.inner and w.flush and w.epochs == 3
    assert isinstance(Wrapper(mce.inner).inner, Learner)


def test_mce_base_agent():
    model = Stub(lambda call: "done")

    class Ex:
        task = TASK

        class learner:
            skill = "## Skill Overview\nCurate."
    ex = Ex()
    ex.model = model
    context = Context()
    context.write("notes.md", "old")
    groups = [Group("q1", [episode("1", ok=True, target="1", question="q1")], target="1"),
              Group("q2", [episode("2", ok=False, target="3", question="q2")], target="3")]
    context.learn(ex, [Raw()(ex, g, context) for g in groups])
    call = model.calls[0]
    assert call["tools"] == fs.TOOLS and "## Skill Overview\nCurate." in call["user"] and "train_accuracy 1/2" in call["user"]
    assert call["system"] == "You are a context engineer working with file tools."


def test_mce_base_data_mounts():
    captured = []

    class Model:
        def run(self, system, user, tools=(), deps=None, rounds=0, **kw):
            captured.append((deps, rounds))

    class Ex:
        task, model = TASK, Model()

        class learner:
            skill = "s"
    context = Context()
    g = Group("q", [episode("7", ok=False, target="8", question="q")], target="8")
    context.learn(Ex(), [Raw()(Ex(), g, context)])
    deps, rounds = captured[0]
    assert rounds == 30 and deps.mounts["context"].store is context and deps.mounts["data"].mode == "ro"
    assert deps.mounts["data"].store.files == {"r1": "is_correct: False\nllm_answer: 7\ntarget: 8\nquestion:\nq"}


def test_skill_in_ace_prompts():
    class Ex:
        task, i, total, training = TASK, 0, 1, True

        class learner:
            skill = "SKILL TEXT"
    model = Stub(schemas={"Reflection": Reflection(lessons=["l"]), "Ops": Ops(ops=[])})
    ex = Ex()
    ex.model = model
    inner = copy.deepcopy(mce_ace.inner)
    x = inner.extract(ex, Group("q", [episode("1", ok=True, target="1")], target="1"), inner.memory)
    inner.memory.learn(ex, [x])
    assert all(c["system"].endswith("Follow this skill as your learning methodology:\n\nSKILL TEXT") for c in model.calls)
    assert len(model.calls) == 2
    assert skilled("SYS", object()) == "SYS"


def test_mce_ace_run():
    model = Stub(lambda call: "SKILL" if "Meta-Level Agent" in call["user"] else right(call),
                 schemas={"Reflection": Reflection(lessons=["l"]), "Ops": Ops(ops=[])})
    run(TASK, mce_ace, model, 2, epochs=2, offline=True)
    metas = [c for c in model.calls if "Meta-Level Agent" in c["user"]]
    assert len(metas) == 2 and "Base-Level (Reflector and Curator)" in metas[0]["user"]
    learning = [c for c in model.calls if c["output"] in (Reflection, Ops)]
    assert len(learning) == 8 and all(c["system"].endswith("\n\nSKILL") for c in learning)


def test_mce_run():
    model = Stub(lambda call: right(call) if call["system"].startswith(TASK.system) else "SKILL")
    run(TASK, swap(mce, every=2), model, 3, epochs=1, offline=True)
    base = [c for c in model.calls if c["tools"] == fs.TOOLS]
    assert len(base) == 2                                   # батч из двух и неполный в конце прохода
    assert "train_accuracy 2/2" in base[0]["user"] and "train_accuracy 1/1" in base[1]["user"]
