"""Обёртки: Gate (правка остаётся, если на val не хуже; решения в логе), Meta (навык перед первой попыткой прохода,
train за проход, откат к лучшей по val, при равенстве первая, без нулевой итерации), swap над обёрткой,
базовый агент MCE (context/ на запись, итоги только текущего батча в data/ на чтение), навык в промптах ACE."""
import copy
import json
from dataclasses import replace

import pytest
from types import SimpleNamespace

from stub import TASK, Stub, episode, right

from ace import fs, verdict
from ace.extract import Raw
from ace.extract.ace import Reflection
from ace.learner import Learner, swap
from ace.loop import Group, Protocol, run
from ace.memory import Lessons
from ace.memory.ace import Ops
from ace.memory.mce import Context
from ace.methods.mce import mce_ace_stand, mce_fs as mce
from ace.wrap.mce import META, MISSING, MetaAgent
from ace.render import skilled
from ace.wrap import Gate, Wrapper
from ace.wrap.mce import Meta

OFFLINE2 = Protocol(offline=True, epochs=2)


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
    meta = Meta(notes("good", "x", "bad", "y", every=2, flush=True, protocol=OFFLINE2), author, "meta")
    run(TASK, meta, model, 3, out=str(tmp_path))
    # навык пишется раз за проход, по истории прошлых итераций; нулевой итерации нет
    assert seen == [[], [("skill 0", 1 / 3, 1.0)]]
    dump = json.load(open(tmp_path / "memory.json"))
    iterations = [r for r in dump if r["kind"] == "iterations"]
    # второй проход: память ухудшилась (bad), val 0 — откат к первой итерации
    assert [(r["text"], r["val"]) for r in iterations] == [("skill 0", 1.0), ("skill 1", 0.0)]
    assert iterations[1]["train"] == 2 / 3
    assert [r["text"] for r in dump if r["kind"] != "iterations"] == ["good", "x"]


def test_meta_train_by_task_check(tmp_path):
    """Доля верных на train для мета-агента — проверка задачи, а не вердикт попытки ученика (вердикт none)."""
    meta = Meta(notes("good", every=3, flush=True, protocol=OFFLINE2, verdict=verdict.none), lambda ex, h: "s", "meta")
    run(TASK, meta, Stub(good_only), 3, out=str(tmp_path))
    dump = json.load(open(tmp_path / "memory.json"))
    assert [r["train"] for r in dump if r["kind"] == "iterations"] == [0.0, 1.0]


def test_meta_tie_keeps_first():
    model = Stub(good_only)
    meta = Meta(notes("good", "x", "good 2", "y", every=3, flush=True, protocol=OFFLINE2), lambda ex, h: "s", "meta")
    ex_learner = []

    class Spy(Meta):
        def on_pass(self, ex):
            super().on_pass(ex)
            ex_learner.append([r.text for r in self.inner.memory.records()])
    spy = Spy(meta.inner, meta.author, "meta")
    run(TASK, spy, model, 3)
    assert ex_learner == [["good"], ["good"]]       # у второй итерации тот же val — следующая начнётся с первой


def test_swap_wrapper():
    w = swap(mce, "mce2", every=2)
    assert isinstance(w, Meta) and w.name == "mce2" and w.every == 2 and mce.every == 20
    assert w.inner is not mce.inner and w.flush and w.protocol.epochs == 3
    assert isinstance(Wrapper(mce.inner).inner, Learner)


class FileAgent(Stub):
    """Заглушка-агент: как агент с файлами, правит FS из deps (act(call, deps)) и отвечает "done"."""
    def __init__(self, act, answer=lambda call: "done", schemas=None):
        super().__init__(answer, schemas)
        self.act = act

    def ask(self, call):
        reply = super().ask(call)
        if isinstance(call.deps, fs.FS):
            self.act(self.calls[-1], call.deps)
        return reply


def write(path, text):
    """act: записать файл, как агент инструментом create."""
    return lambda call, deps: fs.create(SimpleNamespace(deps=deps), path, text)


def meta_writes(skill):
    """Мета-агент пишет SKILL.md по пути из промпта; остальные агенты ничего не делают."""
    def act(call, deps):
        if "Meta-Level Agent" in call["user"]:
            path = call["user"].split("**Write SKILL.md to**: `", 1)[1].split("`", 1)[0]
            fs.create(SimpleNamespace(deps=deps), path, skill)
    return act


class Ex:
    task, epoch, batch, i, skill = TASK, 0, 0, 1, "## Skill Overview\nCurate."

    def solved(self, group):
        return TASK.check(group.answer, group.target)


def test_mce_base_agent():
    model = FileAgent(write("/workspace/iter1_sub0/context/new.md", "lesson"))
    ex = Ex()
    ex.model = model
    context = Context()
    context.write("notes.md", "old")
    groups = [Group("q1", [episode("1", ok=True, target="1", question="q1")], target="1", i=0),
              Group("q2", [episode("2", ok=False, target="3", question="q2")], target="3", i=1)]
    context.learn(ex, [Raw()(ex, g, context) for g in groups])
    call = model.calls[0]
    assert call["tools"] == fs.TOOLS and call["system"] == ""
    assert "**Working Directory**: `/workspace/iter1_sub0`" in call["user"] and "Summary" not in call["user"]
    deps = call["deps"]
    assert deps.mounts["context"].store is context and deps.mounts["data"].mode == deps.mounts[".agent"].mode == "ro"
    assert deps.mounts[".agent"].store.files == {"skills/learning-context/SKILL.md": "## Skill Overview\nCurate."}
    train = json.loads(deps.mounts["data"].store.files["train.json"])
    assert train["summary"] == dict(train_accuracy=0.5, train_metrics=dict(accuracy=0.5), train_total=2, train_errors=0,
                                    batch_idx=0, cumulative_rollouts=2)
    assert train["detailed_results"][1] == dict(id=1, question="q2", ground_truth="3", llm_prediction="2", is_correct=False)
    assert context.files == {"notes.md": "old", "new.md": "lesson"}
    assert context.folder() == {"context/notes.md": "old", "context/new.md": "lesson", "data/train.json": context.train}


def test_meta_agent_asks_for_skill():
    """SKILL.md не записан: просьба в том же разговоре (история прошлого прогона), до трёх раз; потом навык прошлой
    итерации."""
    model = FileAgent(lambda call, deps: None)
    ex = Ex()
    ex.model = model
    author = MetaAgent(META)
    assert author(ex, []) == ""
    assert len(model.calls) == 3 and model.calls[1]["user"] == MISSING.fill(
        expected_path="/workspace/iter1_sub0/.agent/skills/learning-context/SKILL.md")
    assert "VALIDATION ERROR" in model.calls[2]["user"] and model.calls[0]["history"] is None
    # записал со второго раза
    model = FileAgent(lambda call, deps: len(model.calls) == 2 and write(
        "/workspace/iter1_sub0/.agent/skills/learning-context/SKILL.md", "S")(call, deps))
    ex.model = model
    assert author(ex, []) == "S" and len(model.calls) == 2


def test_mce_run():
    model = FileAgent(meta_writes("## Skill Overview\nS"), lambda call: right(call) if call["system"].startswith(TASK.system)
                      else "done")
    run(TASK, swap(mce, every=2, protocol=replace(mce.protocol, epochs=1)), model, 3)
    base = [c for c in model.calls if c["user"].startswith("# Context Engineer")]
    assert len(base) == 2                                   # батч из двух и неполный в конце прохода
    summaries = [json.loads(c["deps"].mounts["data"].store.files["train.json"])["summary"] for c in base]
    assert [(s["batch_idx"], s["train_total"], s["cumulative_rollouts"]) for s in summaries] == [(0, 2, 2), (1, 1, 3)]
    assert "`/workspace/iter1_sub1`" in base[1]["user"]


def test_skill_in_ace_prompts():
    class Ex:
        task, i, total, training, skill = TASK, 0, 1, True, "SKILL TEXT"
    model = Stub(schemas={"Reflection": Reflection(lessons=["l"]), "Ops": Ops(ops=[])})
    ex = Ex()
    ex.model = model
    inner = copy.deepcopy(mce_ace_stand.inner)
    x = inner.extract(ex, Group("q", [episode("1", ok=True, target="1")], target="1"), inner.memory)
    inner.memory.learn(ex, [x])
    assert all(c["system"].endswith("Follow this skill as your learning methodology:\n\nSKILL TEXT") for c in model.calls)
    assert len(model.calls) == 2
    assert skilled("SYS", object()) == "SYS"


def test_mce_ace_run():
    model = FileAgent(meta_writes("SKILL"), lambda call: right(call) if call["system"].startswith(TASK.system) else "done",
                      schemas={"Reflection": Reflection(lessons=["l"]), "Ops": Ops(ops=[])})
    run(TASK, swap(mce_ace_stand, protocol=OFFLINE2), model, 2)
    metas = [c for c in model.calls if "Meta-Level Agent" in c["user"]]
    assert len(metas) == 2 and "Base-Level (Reflector and Curator)" in metas[0]["user"]
    learning = [c for c in model.calls if c["output"] in (Reflection, Ops)]
    assert len(learning) == 8 and all(c["system"].endswith("\n\nSKILL") for c in learning)


def test_meta_offline_only():
    """MCE учится только на train: онлайн-протокол — ошибка сборки, и при замене тоже."""
    with pytest.raises(ValueError, match="офлайн"):
        Meta(notes(), lambda ex, h: "", "meta")
    with pytest.raises(ValueError, match="офлайн"):
        swap(mce, protocol=Protocol())
