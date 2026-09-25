"""EvoLib: баллы по голосованию или судье, IG и Future IG, insight с делением баллов, улучшение и сравнение
решений; библиотека skills / insights со слиянием похожих и журналом Future IG; показ по весу."""
import math
import random

import numpy as np
from stub import TASK, Stub, episode

from ace import prompts, verdict
from ace.extract import ATTRIBUTION, BEST_ANSWER, IG, Extraction
from ace.extract.evolib import Attribution, Best, Gains, future_gains, log_gain
from ace.loop import Group, run
from ace.methods.evolib import SHOW, Library, Skill, evolib_judge, insight_weight, skill_weight

SKILL = "<subtask>\n<description>{}</description>\n<solution>s</solution>\n<result>r</result>\n</subtask>"


class Ex:
    task, training = TASK, True

    def __init__(self, model):
        self.model = model


def group(answers, vote=True, oks=None, shown=None):
    eps = [episode(a, ok=oks[k] if oks else None, final=f"solution {k}\nFINAL ANSWER: {a}", k=k,
                   shown=shown[k] if shown else ()) for k, a in enumerate(answers)]
    g = Group("q", eps)
    if vote:
        verdict.vote(None, g)
    return g


def test_gains():
    assert log_gain(1, [1, 1, 1]) == 0
    assert math.isclose(log_gain(1, [1, 1, 0]), math.log(1.5))
    assert math.isclose(log_gain(1, [1, 0, 0]), math.log(3))
    assert log_gain(0, [0, 0]) == 0
    a = Attribution([["r1", "r1", "r2"], ["r2"], []], 0)
    assert future_gains(a, [1, 0, 0.5]) == [("r1", math.log(4)), ("r1", math.log(4)), ("r2", math.log(2))]


def test_unevaluated():
    """Без оценки: баллы по большинству, лучшая — первая из согласных; insight есть — баллы пополам; IG до деления;
    лучшего решения ещё нет — улучшает."""
    model = Stub(lambda call: "```insight\nIf units differ, then convert.\n```")
    x = Gains()(Ex(model), group(["1", "2", "2"], shown=[["r1"], ["r2"], []]), Library())
    assert x.scores == [0, 0.5, 0.5] and math.isclose(x.extras[IG], math.log(1.5))
    assert x.lessons == ["If units differ, then convert."] and "solution 1" in model.calls[0]["user"]
    assert x.extras[BEST_ANSWER] == Best("solution 1\nFINAL ANSWER: 2", "2", 0.5)
    assert x.extras[ATTRIBUTION] == Attribution([["r1"], ["r2"], []], 1)


def test_no_insight_keeps_scores():
    x = Gains()(Ex(Stub(lambda call: "N/A")), group(["1", "1", "2"]), Library())
    assert x.lessons == [] and x.scores == [1, 1, 0]


def test_improving_and_compare():
    """Старое решение не хуже по баллу: не улучшает; если оно не сходится с большинством — решает сравнение."""
    memory = Library()
    memory.solutions["q"] = Best("old solution", "2", 1.0)
    model = Stub(lambda call: "```judgment\nSolution 2 is better.\n```" if "two solutions" in call["user"] else "N/A")
    x = Gains()(Ex(model), group(["2", "2", "3"]), memory)
    assert x.extras[BEST_ANSWER] is None and len(model.calls) == 1        # ответ тот же: сравнения нет
    memory.solutions["q"] = Best("old solution", "7", 1.0)
    x = Gains()(Ex(model), group(["2", "2", "3"]), memory)
    assert "old solution" in model.calls[-1]["user"] and x.extras[BEST_ANSWER].answer == "2"
    model = Stub(lambda call: "```judgment\nSolution 1\n```" if "two solutions" in call["user"] else "N/A")
    assert Gains()(Ex(model), group(["2", "2", "3"]), memory).extras[BEST_ANSWER] is None


def test_evaluated():
    """С оценкой: баллы по вердикту попытки, insight только при неудаче лучшей и с её вердиктом, без деления."""
    model = Stub(lambda call: "<insight>If a, then b.</insight>")
    x = Gains(evaluated=True)(Ex(model), group(["1", "2", "3"], vote=False, oks=[False, True, True]), Library())
    assert model.calls == [] and x.scores == [0, 1, 1] and x.extras[ATTRIBUTION].best == 1
    x = Gains(evaluated=True)(Ex(model), group(["1", "2", "3"], vote=False, oks=[False] * 3), Library())
    assert "Evaluation: wrong" in model.calls[0]["user"] and x.lessons == ["If a, then b."] and x.scores == [0, 0, 0]


def fake_embed(monkeypatch, vecs):
    monkeypatch.setattr("ace.embed.embed", lambda texts: np.array([vecs[t] for t in texts], dtype=float))


def extraction(insight=None, best=None, ig=0.5, shown=([], [], []), scores=(1, 0, 0), b=0):
    return Extraction(Group("q", []), [insight] if insight else [], list(scores),
                      {IG: ig, BEST_ANSWER: best, ATTRIBUTION: Attribution([list(s) for s in shown], b)})


def test_library_learn(monkeypatch):
    """insight, лучшее решение (скрыто) и skills из него с IG, Future IG в журнал записи из промпта лучшей."""
    fake_embed(monkeypatch, {"a": [1, 0], "d1": [0, 1], "d2": [1, 0]})
    m = Library()
    best = Best("Plan.\n" + SKILL.format("d1") + "\n" + SKILL.format("d2") + "\nFINAL ANSWER: 1", "1", 1.0)
    m.learn(Ex(Stub()), [extraction("If a, then b.", best, ig=0.4)])
    assert [(r.id, type(r).__name__) for r in m.records()] == [("r1", "Insight"), ("r2", "Skill"), ("r3", "Skill")]
    assert m.get("r2").doc == "d1" and m.get("r2").ig == 0.4 and m.best("q") is best
    assert all(r.text != best.output for r in m.records())
    m.learn(Ex(Stub()), [extraction(shown=[["r1", "r1", "r3"], ["r3"], []], scores=[1, 0, 0.5])])
    assert m.get("r1").outcomes == [math.log(4), math.log(4)] and m.get("r3").outcomes == [math.log(2)]
    assert m.best("q") is best                                             # не улучшило — старое остаётся
    assert [d["kind"] for d in m.dump()] == ["skill", "skill", "insight", "best"]


def test_merge_insight(monkeypatch):
    """Похожий insight (косинус условий > 0.8) сливает модель: одна слитая запись наследует журнал, старая уходит;
    несколько — старая остаётся, новые делят один журнал."""
    fake_embed(monkeypatch, {"a": [1, 0], "a2": [0.9, 0.436]})
    m = Library()
    m.insights.add("If a, then b.", outcomes=[0.3])
    one = Stub(lambda call: "```insights\nIf a or a2, then b.\n```")
    m.add_insight(Ex(one), "If a2, then c.")
    assert "If a, then b.\nIf a2, then c." in one.calls[0]["user"]
    assert [(r.text, r.outcomes) for r in m.records()] == [("If a or a2, then b.", [0.3])]
    fake_embed(monkeypatch, {"a or a2": [1, 0], "a2": [0.9, 0.436], "x": [1, 0], "y": [0, 1]})
    two = Stub(lambda call: "```insights\nIf x, then 1.\nIf y, then 2.\nnot an insight\n```")
    m.add_insight(Ex(two), "If a2, then c.")
    texts = [r.text for r in m.records()]
    assert texts == ["If a or a2, then b.", "If x, then 1.", "If y, then 2."]
    assert m.records()[1].outcomes is m.records()[2].outcomes


def test_merge_skill(monkeypatch):
    """Слитый skill: IG — скользящее среднее с долей 0.5, журнал старого."""
    fake_embed(monkeypatch, {"d1": [1, 0], "d1b": [1, 0], "d": [1, 0]})
    m = Library()
    m.skills.add(SKILL.format("d1"), doc="d1", ig=1.0, outcomes=[0.2])
    m.add_skill(Ex(Stub(lambda call: SKILL.format("d"))), SKILL.format("d1b"), "d1b", 0.0)
    [r] = m.records()
    assert (r.doc, r.ig, r.outcomes) == ("d", 0.5, [0.2])


def test_weights_and_show():
    s = Skill("r1", "x", outcomes=[], ig=-1.0)
    assert math.isclose(skill_weight(s), 0.51) and skill_weight(Skill("r2", "x", outcomes=[-5.0], ig=-1.0)) == 0.01
    assert math.isclose(insight_weight(Skill("r3", "x", outcomes=[0.2, 0.4])), 0.3)
    m = Library()
    m.insights.add("If a, then b.")
    random.seed(1)                  # первое число 0.13: ветка skills пуста, ход переходит к insights
    p = SHOW.prompt(Ex(Stub()), m, {"context": "q"}, 0)
    assert p.system.startswith(prompts.text("evolib_subtasks") + "\n\n" + prompts.text("evolib_insights_intro"))
    assert p.shown == ["r1"] and SHOW.random


def test_judge_after_each_attempt():
    """Судья ставит вердикт сразу после попытки (DEVIATIONS D7), в зачёт — ответ большинства."""
    model = Stub(lambda call: "VERDICT: correct" if call["system"] == "You are a strict grader." else "N/A")
    run(TASK, evolib_judge, model, 1)
    kinds = ["judge" if c["system"] == "You are a strict grader." else "solver" if c["system"].startswith(TASK.system)
             else "other" for c in model.calls]
    assert kinds == ["solver", "judge"] * 3
