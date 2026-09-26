"""EvoLib: баллы по голосованию или судье, IG и Future IG, insight с делением баллов, улучшение и сравнение
решений; библиотека skills / insights со слиянием похожих и журналом Future IG; показ по весу."""
import math
import random

from stub import TASK, Stub, episode, experiment, fake_embed

from ace import verdict
from ace.extract import ATTRIBUTION, BEST_ANSWER, IG, Extraction
from ace.extract.evolib import Attribution, Best, Gains
from ace.upstream.evolib import log_gain
from ace.learner import swap
from ace.loop import Group, run
from ace.memory.evolib import Skill, SkillLibrary, future_gains
from ace.methods.evolib import evolib, evolib_judge
from ace.solver.evolib import SAMPLER, insight_weight, skill_weight

SKILL = "<subtask>\n<description>{}</description>\n<solution>s</solution>\n<result>r</result>\n</subtask>"


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
    x = Gains()(experiment(model), group(["1", "2", "2"], shown=[["r1"], ["r2"], []]), SkillLibrary())
    assert x.scores == [0, 0.5, 0.5] and math.isclose(x.extras[IG], math.log(1.5))
    assert x.lessons == ["If units differ, then convert."] and "solution 1" in model.calls[0]["user"]
    assert x.extras[BEST_ANSWER] == Best("solution 1\nFINAL ANSWER: 2", "2", 0.5)
    assert x.extras[ATTRIBUTION] == Attribution([["r1"], ["r2"], []], 1)


def test_no_insight_keeps_scores():
    x = Gains()(experiment(Stub(lambda call: "N/A")), group(["1", "1", "2"]), SkillLibrary())
    assert x.lessons == [] and x.scores == [1, 1, 0]


def test_improving_and_compare():
    """Память решает, улучшает ли лучшее решение: старого нет или новое строго лучше по баллу; старое не хуже и
    сходится с большинством — нет; не сходится — решает сравнение (после слияния insight)."""
    def learn(old, judgment):
        memory = SkillLibrary()
        memory.solutions["q"] = old
        model = Stub(lambda call: judgment if "two solutions" in call["user"] else "N/A")
        g = group(["2", "2", "3"])
        new = Gains()(experiment(model), g, memory).extras[BEST_ANSWER]
        memory.learn(experiment(model), [Extraction(g, [], [1, 1, 0], {IG: 0, BEST_ANSWER: new, ATTRIBUTION: Attribution([[]] * 3, 0)})])
        return memory.best("q") is new, [c["user"] for c in model.calls]
    improved, calls = learn(Best("old", "2", 1.0), "")
    assert not improved and len(calls) == 1                            # только insight: сравнения нет
    improved, calls = learn(Best("old solution", "7", 1.0), "```judgment\nSolution 2 is better.\n```")
    assert improved and "old solution" in calls[-1]
    assert not learn(Best("old solution", "7", 1.0), "```judgment\nSolution 1\n```")[0]
    assert learn(Best("old", "7", 0.5), "") == (True, calls[:1])     # новое лучше по баллу


def test_evaluated():
    """С оценкой: баллы по вердикту попытки, insight только при неудаче лучшей и с её вердиктом, без деления."""
    model = Stub(lambda call: "<insight>If a, then b.</insight>")
    x = Gains(evaluated=True)(experiment(model), group(["1", "2", "3"], vote=False, oks=[False, True, True]), SkillLibrary())
    assert model.calls == [] and x.scores == [0, 1, 1] and x.extras[ATTRIBUTION].best == 1
    x = Gains(evaluated=True)(experiment(model), group(["1", "2", "3"], vote=False, oks=[False] * 3), SkillLibrary())
    assert "Evaluation: wrong" in model.calls[0]["user"] and x.lessons == ["If a, then b."] and x.scores == [0, 0, 0]




def extraction(insight=None, best=None, ig=0.5, shown=([], [], []), scores=(1, 0, 0), b=0):
    return Extraction(Group("q", []), [insight] if insight else [], list(scores),
                      {IG: ig, BEST_ANSWER: best, ATTRIBUTION: Attribution([list(s) for s in shown], b)})


def test_library_learn(monkeypatch):
    """insight, лучшее решение (скрыто) и skills из него с IG, Future IG в журнал записи из промпта лучшей."""
    fake_embed(monkeypatch, {"a": [1, 0], "<description>d1</description>": [0, 1], "<description>d2</description>": [1, 0]})
    m = SkillLibrary()
    best = Best("Plan.\n" + SKILL.format("d1") + "\n" + SKILL.format("d2") + "\nFINAL ANSWER: 1", "1", 1.0)
    m.learn(experiment(Stub()), [extraction("If a, then b.", best, ig=0.4)])
    assert [(r.id, type(r).__name__) for r in m.records()] == [("r1", "Insight"), ("r2", "Skill"), ("r3", "Skill")]
    assert m.get("r2").doc == "<description>d1</description>" and m.get("r2").ig == 0.4 and m.best("q") is best
    assert all(r.text != best.output for r in m.records())
    m.learn(experiment(Stub()), [extraction(shown=[["r1", "r1", "r3"], ["r3"], []], scores=[1, 0, 0.5])])
    assert m.get("r1").outcomes == [math.log(4), math.log(4)] and m.get("r3").outcomes == [math.log(2)]
    assert m.best("q") is best                                             # не улучшило — старое остаётся
    assert [d["kind"] for d in m.dump()] == ["skill", "skill", "insight", "best"]


def test_merge_insight(monkeypatch):
    """Похожий insight (косинус условий > 0.8) сливает модель: одна слитая запись наследует журнал, старая уходит;
    несколько — старая остаётся, новые делят один журнал."""
    fake_embed(monkeypatch, {"a": [1, 0], "a2": [0.9, 0.436], "a or a2": [1, 0]})
    m = SkillLibrary()
    m.add(m.insights, "If a, then b.", [1, 0], outcomes=[0.3])
    one = Stub(lambda call: "```insights\nIf a or a2, then b.\n```")
    m.add_insight(experiment(one), "If a2, then c.")
    assert "If a, then b.\nIf a2, then c." in one.calls[0]["user"]
    assert [(r.text, r.outcomes) for r in m.records()] == [("If a or a2, then b.", [0.3])]
    fake_embed(monkeypatch, {"a or a2": [1, 0], "a2": [0.9, 0.436], "x": [1, 0], "y": [0, 1]})
    two = Stub(lambda call: "```insights\nIf x, then 1.\nIf y, then 2.\nnot an insight\n```")
    m.add_insight(experiment(two), "If a2, then c.")
    texts = [r.text for r in m.records()]
    assert texts == ["If a or a2, then b.", "If x, then 1.", "If y, then 2."]
    assert m.records()[1].outcomes is m.records()[2].outcomes


def test_merge_skill(monkeypatch):
    """Слитый skill: IG — скользящее среднее с долей 0.5, журнал старого."""
    fake_embed(monkeypatch, {"d1": [1, 0], "d1b": [1, 0], "<description>d</description>": [1, 0]})
    m = SkillLibrary()
    m.add(m.skills, SKILL.format("d1"), [1, 0], doc="d1", ig=1.0, outcomes=[0.2])
    m.add_skills(experiment(Stub(lambda call: SKILL.format("d"))), [(SKILL.format("d1b"), "d1b")], 0.0)
    [r] = m.records()
    assert (r.doc, r.ig, r.outcomes) == ("<description>d</description>", 0.5, [0.2])


def test_weights_and_show():
    s = Skill("r1", "x", outcomes=[], ig=-1.0)
    assert math.isclose(skill_weight(s), 0.51) and skill_weight(Skill("r2", "x", outcomes=[-5.0], ig=-1.0)) == 0.01 - 5.0
    assert math.isclose(insight_weight(Skill("r3", "x", outcomes=[0.2, 0.4])), 0.3)
    m = SkillLibrary()
    m.insights.add("If a, then b.")
    random.seed(1)                  # первое число 0.13: ветка skills пуста, ход переходит к insights
    p = SAMPLER.prompt(experiment(Stub()), m, {"question": "q"}, 0)
    user = p.solver.call("").messages[0]["content"]
    assert "Problem: q\n\nHere are some insights that may help you solve the problem:\nIf a, then b.\n" in user
    assert p.shown == ["r1"] and SAMPLER.random and swap(evolib, solver=SAMPLER).key() is None
    random.seed(0)                  # первое число 0.84: выше обоих порогов — ничего
    assert SAMPLER.prompt(experiment(Stub()), m, {"question": "q"}, 0).shown == []


def test_judge_after_each_attempt():
    """Судья ставит вердикт сразу после попытки (масштабы не смешиваются), в зачёт — ответ большинства."""
    model = Stub(lambda call: "VERDICT: correct" if call["system"] == "You are a strict grader." else "N/A")
    run(TASK, evolib_judge, model, 1)
    kinds = ["judge" if c["system"] == "You are a strict grader." else "solver" if "plan ahead how to break down" in c["user"]
             else "other" for c in model.calls]
    assert kinds == ["solver", "judge"] * 3
