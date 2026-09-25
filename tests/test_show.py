"""Показ: весь текст, top-k, выборка по весу, выбор ветки, синтез, каталог с чтением, урок после ошибки."""
import random

import numpy as np
from stub import Stub

from ace import fs, parse, prompts
from ace.learner import Learner
from ace.loop import Attempt, Prompt
from ace.memory import Lessons
from ace.model import Patch, Reader, Step
from ace.show import HEAD, AfterError, Catalog, Choose, Sample, Show, Synth, TopK, Whole

ITEM = {"context": "What is 2 / 4?", "target": "0.5"}


class Ex:
    model = Stub(lambda call: "<cheatsheet>short</cheatsheet>")


def memory(*texts):
    m = Lessons()
    for t in texts:
        m.add(t)
    return m


def test_whole():
    assert Whole().prompt(Ex, memory(), ITEM, 0) == Prompt()
    p = Whole().prompt(Ex, memory("a", "b"), ITEM, 0)
    assert p.system == "\n\n" + HEAD + "[r1] a\n[r2] b" and p.shown == ["r1", "r2"]
    assert Whole(empty="(empty)").prompt(Ex, memory(), ITEM, 0).system == "\n\n" + HEAD + "(empty)"
    assert Whole(head="", before="B:", after="!").prompt(Ex, memory("a"), ITEM, 0).system == "\n\nB:[r1] a!"


def test_topk(monkeypatch):
    vecs = {"far": [0, 1], "near": [1, 0], "mid": [0.8, 0.6], ITEM["context"]: [1, 0]}
    monkeypatch.setattr("ace.embed.embed", lambda texts: np.array([vecs[t] for t in texts], dtype=float))
    p = TopK(2).prompt(Ex, memory("far", "near", "mid"), ITEM, 0)
    assert p.shown == ["r2", "r3"]


def test_sample_is_random():
    random.seed(0)
    show = Sample(3, weight=lambda r: 1.0 if r.text == "x" else 0.0)
    assert show.random and Learner("x", show=show).key() is None
    assert show.prompt(Ex, memory("x", "y"), ITEM, 0).shown == ["r1", "r1"]
    assert Learner("x").key() == ()


def test_choose():
    """Пустая ветка отдаёт ход следующей; число выше всех порогов — ничего."""
    full = Whole(head="")
    random.seed(0)                          # первое число 0.84
    assert Choose((0.9, Show()), (1.0, full)).prompt(Ex, memory("a"), ITEM, 0).shown == ["r1"]
    random.seed(0)
    assert Choose((0.5, full)).prompt(Ex, memory("a"), ITEM, 0) == Prompt()


def test_synth():
    fields = lambda text, memory, item: dict(PREVIOUS_INPUT_OUTPUT_PAIRS=text, NEXT_INPUT=item["context"], PREVIOUS_CHEATSHEET="")
    show = Synth(Whole(empty="(empty)"), prompts.load("dc_synth"), fields, Reader(text=parse.opened("cheatsheet")), tokens=2)
    p = show.prompt(Ex, memory(), ITEM, 0)
    assert p.system == "\n\n" + HEAD + "short"
    assert ITEM["context"] in Ex.model.calls[-1]["user"]


def test_catalog():
    m = memory("Check units.\nbody", "Guard division.")
    p = Catalog().prompt(Ex, m, ITEM, 0)
    assert p.tools == fs.READ_TOOLS and p.shown == [] and p.rounds == 3
    assert "skills/r1  Check units." in p.system and "skills/r2  Guard division." in p.system
    assert "body" not in p.system

    class Ctx:
        deps = p.deps
    fs.read(Ctx, "skills/r2")
    assert p.deps.reads == ["r2"]


def test_after_error():
    m = memory("Check the denominator.")
    show = AfterError(Whole(), lambda mem: mem.records(), trigger=lambda r: "zerodivisionerror")
    a = Attempt("q", 0, True, Prompt())
    assert show.watches_steps
    assert show.on_step(Ex, m, a, Step("run_python", "{}", "1.0")) is None
    patch = show.on_step(Ex, m, a, Step("run_python", "{}", "Traceback ...\nZeroDivisionError: division by zero"))
    assert patch == Patch(append="Known fix for this error:\n- Check the denominator.")
    assert show.on_step(Ex, m, a, Step("run_python", "{}", "Traceback ...\nKeyError: 'x'")) is None
