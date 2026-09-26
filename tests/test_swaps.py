"""Абляция одной заменой и мета над учеником (таблица замен ревью): каждая клетка — либо ошибка сборки с причиной,
либо прогон на заглушке без ошибок. Молча не действующих и падающих в работе клеток нет."""
import json

import numpy as np
import pytest
from stub import TASK, Stub

from ace import config, verdict
from ace.env import Sandbox
from ace.extract import Raw
from ace.learner import swap
from ace.loop import Attempts, Protocol, run, spread, vote
from ace.memory import Lessons
from ace.methods import METHODS
from ace.show import Whole
from ace.wrap import Wrapper
from ace.wrap.gepa import Evolution
from ace.wrap.mce import Meta

OFFLINE = Protocol(offline=True, epochs=2)
LEVELS = {
    "solver": dict(solver=None),
    "show": dict(show=Whole()),
    "extract": dict(extract=Raw()),
    "memory": dict(memory=Lessons()),
    "attempts T": dict(attempts=Attempts(3, spread, vote)),
    "attempts n": dict(attempts=Attempts(3)),
    "verdict none": dict(verdict=verdict.none),
    "verdict judge": dict(verdict=verdict.judge),
    "group vote": dict(group_verdict=verdict.vote),
    "every": dict(every=5),
    "protocol": dict(protocol=OFFLINE),
    "env": dict(env=Sandbox()),
}
BASES = ["ace", "ace_stand", "dc", "dc_rs", "scope", "tfgrpo", "evolib", "mce", "mce_fs", "gepa", "ace_stand_hooks"]
ANSWER = "FINAL ANSWER: 0\n<cheatsheet>x</cheatsheet>\n```\nX\n```"     # и решателю, и рефлексии, и куратору


def learner_of(method):
    while isinstance(method, Wrapper):
        method = method.inner
    return method


@pytest.fixture(autouse=True)
def stub_embeddings(monkeypatch):
    monkeypatch.setattr("ace.embed.embed", lambda texts: np.array([[len(t) % 7 + 1.0, 1.0] for t in texts]))
    monkeypatch.setattr(config, "VAL_SIZE", 2)


def runs_clean(learner, tmp_path):
    """Прогон на заглушке без ошибок в логе; агенты Claude SDK (память-папка mce) и контейнер (Sandbox) — только
    сборка."""
    if learner.memory.placed or learner.env.tools:
        return
    summary = run(TASK, learner, Stub(lambda call: ANSWER), 2, str(tmp_path))
    errors = [r["error"].strip().splitlines()[-1] for r in json.load(open(tmp_path / "log.json"))
              if r["finish"] == "error"]
    assert errors == [] and summary["n"] == 2


@pytest.mark.parametrize("name", BASES)
@pytest.mark.parametrize("level", LEVELS)
def test_one_swap(name, level, tmp_path):
    try:
        learner = swap(METHODS[name], f"{name}_x", **LEVELS[level])
    except ValueError as error:         # Contract — тоже ValueError; причина — после имени ученика
        assert ": " in str(error), error
        return
    runs_clean(learner, tmp_path)


@pytest.mark.parametrize("name", BASES)
@pytest.mark.parametrize("wrap", ["Evolution", "Meta"])
def test_meta_over_learner(name, wrap, tmp_path):
    """Evolution и Meta над учеником метода (протокол — офлайн, как им нужно)."""
    base = swap(learner_of(METHODS[name]) if wrap == "Meta" else METHODS[name], protocol=OFFLINE)
    try:
        learner = Evolution(base, 20) if wrap == "Evolution" else Meta(base, lambda ex, h: "SKILL")
        learner.check_placed()
    except ValueError as error:
        assert ": " in str(error), error
        return
    runs_clean(learner, tmp_path)
