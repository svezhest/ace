"""Мостик к EvoLib (98266b2, эталоны bridge/fixtures/evolib, снятые bridge/capture_evolib.py): промпты, разборщики,
операции над библиотекой, run_iteration и цикл на 4 задачах в два прохода. Входы разборщиков и памяти — те же,
что в скрипте снятия; задача — hmmt (тексты и параметры апстрима), проверка — строковая, как eval_function скрипта
снятия. Разборщики кода (extract_functions, CODE_*, BIGCODE_*) не сравниваются: у нас вариант HMMT.
Эмбеддинги — та же таблица «подстрока -> вектор»."""
import importlib
import math
import random

import numpy as np
import pytest
from upstream import deviation, fixture

from ace import parse, prompts, verdict
from ace.extract import ATTRIBUTION, BEST_ANSWER, IG
from ace.extract.evolib import Attribution, Best, Gains, future_gains, insight_of, log_gain, second_better
from ace.learner import swap
from ace.loop import Episode, Group, Prompt, Protocol, run
from ace.model import roles, text_reply
from ace.tasks import TASKS

extract_evolib = importlib.import_module("ace.extract.evolib")
E = importlib.import_module("ace.methods.evolib")      # модуль: имя в пакете занято самим методом
MEM = importlib.import_module("ace.memory.evolib")
SHOW = importlib.import_module("ace.show.evolib")

PROMPTS, PARSERS, MEMORY, LOOP = (fixture("evolib", n) for n in ("prompts", "parsers", "memory", "loop"))
REASONING = {"max_completion_tokens": 50000, "reasoning_effort": "high"}
SOLVER_HEAD = "You are a math expert. For the following math problem"


def solution(desc, result, answer):
    """bridge/capture_evolib.py:solution."""
    return (f"<subtask>\n<description>\n{desc}\n</description>\n<solution>\nwork\n</solution>\n"
            f"<result>{result}</result>\n</subtask>\n<answer>{answer}</answer>")


def no_math(text):
    """Промпты апстрима без «math» — у задач стенда: они не только математические."""
    deviation("S2")
    return text.replace("a math expert", "an expert").replace("math ", "")


def no_evaluation(text):
    """Строка вердикта лучшей попытки в промпте insight — вариант evolib_judge стенда (methods/evolib.py): у HMMT
    апстрима test_result в промпт не идёт, и метода «EvoLib с оценкой» у него нет."""
    if "\nEvaluation: " not in text:
        return text
    head, tail = text.split("\nEvaluation: ", 1)
    return head + tail.split("\n", 1)[1]


upstream_answer = SHOW.upstream_answer


def table_embed(monkeypatch, table, default=(0.0, 0.0, 1.0)):
    """bridge/fake.py:TableEmbed: первая подстрока из таблицы -> вектор."""
    def embed(texts):
        return np.array([next((v for k, v in table if k in t), default) for t in texts], dtype=float)
    monkeypatch.setattr("ace.embed.embed", embed)


class Fake:
    """Модель: rules — пары (имя, маркер или функция (system, user), ответ или функция от user)."""
    name = "fake"

    def __init__(self, rules, default="N/A"):
        self.rules, self.default, self.calls = rules, default, []

    def ask(self, call):
        system, user = roles(call.messages)
        name, text = next(((n, r(user) if callable(r) else r) for n, m, r in self.rules
                           if (m(system, user) if callable(m) else m in user)), ("default", self.default))
        self.calls.append(dict(name=name, system=system, user=user, params=call.params))
        return text_reply(call, text)

    def embed(self, texts, name):
        return np.asarray(importlib.import_module("ace.embed").embed(texts)).tolist()

    def usage(self):
        return dict(calls=len(self.calls), prompt_tokens=0, completion_tokens=0)


def cycle(replies):
    state = {"i": 0}

    def reply(_):
        state["i"] += 1
        return replies[(state["i"] - 1) % len(replies)]
    return reply


class Task:
    """Задачи эталона под именем hmmt; проверка — как eval_function скрипта снятия (вместо matharena): последний
    <answer> решения против строки-цели; ответ без тегов сравнивается как есть."""
    name, system, instr = "hmmt", "You solve problems.", "Solve the problem."

    def __init__(self, problems):
        self.items = [dict(context=p, target=a) for p, a in problems]

    def load(self, split="", size=None):
        return self.items

    def check(self, answer, target):
        if "<answer>" in (answer or ""):
            answer = answer.rsplit("<answer>", 1)[1].split("</answer>", 1)[0].replace("$", "").strip()
        return bool(answer) and answer == str(target)


class Ex:
    training = True

    def __init__(self, model, task=Task([])):
        self.model, self.task = model, task


def state(m):
    """Библиотека, как её пишет эталон: skill -> [IG, Future IG, description], insight -> Future IG; порядок — как в dict."""
    return ([(r.text, [r.ig, list(r.outcomes), r.doc]) for r in m.skills.records()],
            [(r.text, list(r.outcomes)) for r in m.insights.records()])


def upstream_state(skills, insights):
    """skills: текст -> [IG, Future IG, description, ...]; insights: текст -> Future IG."""
    return [(t, v[:3]) for t, v in skills.items()], list(insights.items())


def figs(insight_lib):
    return {t: v[0] for t, v in insight_lib.items()}

# промпты


@pytest.mark.parametrize("task", ["hmmt", "formula"])
def test_prompts_filled(task):
    """У hmmt — тексты апстрима дословно, у задач стенда — без «math»."""
    f, sol1, sol2 = PROMPTS["filled"], solution("Add 2 and 3.", "5", "5"), solution("Add 2 and 3.", "6", "6")
    same = (lambda t: t) if task == "hmmt" else no_math
    d = extract_evolib.domain(TASKS[task])
    insights = ["If adding integers, then do check the carry.", "If adding decimals, then do align the point."]
    insight = prompts.load("evolib_insight").fill(question="Compute 2+3.", solution=sol1, evaluation="", **d)
    assert insight == same(f["insight_generation"]) == same(f["insight_generation_with_test_result"])
    assert prompts.load("evolib_merge_skills").fill(skills="\n".join([sol1, sol2]), **d) == same(f["skill_consolidation"])
    assert prompts.load("evolib_merge_insights").fill(insights="\n".join(insights), **d) == same(f["insight_consolidation"])
    assert prompts.load("evolib_compare").fill(question="Compute 2+3.", a=sol1, b=sol2, **d) == same(f["solution_comparison"])


def solver_call(p):
    return p.solver.call("")


@pytest.mark.parametrize("name,skills,insights", [("solver_empty", 0, 0), ("solver_skills", 1, 0),
                                                   ("solver_insights", 0, 1), ("solver_both_skills_win", 1, 1)])
def test_solver_section(monkeypatch, name, skills, insights):
    m = MEM.Library()
    if skills:
        m.skills.add(solution("Add two integers a and b.", "5", "5"), doc="d", ig=0.0)
    if insights:
        m.insights.add("If adding integers, then do check the carry.")
    monkeypatch.setattr(random, "random", lambda: 0.1 if skills else 0.5)
    call = solver_call(SHOW.SHOW.prompt(Ex(None), m, {"context": "Compute 2+3."}, 0))
    assert call.messages == [{"role": "user", "content": PROMPTS["filled"][name]}] and call.params == REASONING

# разборщики


SUBTASKS = {
    "one": solution("Add a and b.", "5", "5"),
    "two": solution("Add a and b.", "5", "5") + "\n" + solution("Multiply a and b.", "6", "6"),
    "no_close": "<subtask>\n<description>x</description>\n",
    "no_description": "<subtask>\n<solution>y</solution>\n</subtask>",
    "one_without_description_among_two": solution("Add a and b.", "5", "5") + "\n<subtask>no desc</subtask>",
    "two_descriptions": "<subtask><description> a </description><description>b</description></subtask>",
    "upper_case": "<SUBTASK><description>x</description></SUBTASK>",
    "nested": "<subtask><subtask><description>in</description></subtask></subtask>",
    "empty": "",
}
FENCED = {
    "one": "```insights\nIf a, then b.\n```",
    "two": "```insights\nIf a, then b.\n```\ntext\n```insights\nIf c, then d.\n```",
    "no_close": "```insights\nIf a, then b.\n",
    "upper_case": "```INSIGHTS\nIf a, then b.\n```",
    "other_tag_between": "```python\nx=1\n```\n```insights\nIf a, then b.\n```",
    "tag_prefix": "```insightsx\nIf a, then b.\n```",
    "inner_fence": "```insights\nIf a, then use ```code```.\n```",
    "empty": "",
}
CONDITIONS = {"normal": "If the sum is odd, then do check parity.", "two_then": "If a, then b, then c.", "no_then": "If a and b.",
              "lower_if": "if a, then b.", "if_inside": "If x, then If y.", "then_without_comma": "If a then b.", "empty": ""}
INSIGHT_REPLIES = {
    "fenced": "```insight\nIf a, then b.\n```",
    "tag": "<mistake>m</mistake>\n<insight>\nIf a, then b.\n</insight>",
    "tag_and_fenced": "<insight>If tag, then t.</insight>\n```insight\nIf fenced, then f.\n```",
    "two_tags": "<insight>If one, then 1.</insight><insight>If two, then 2.</insight>",
    "na": "<insight>\nN/A\n</insight>",
    "na_with_text": "<insight>N/A, I agree</insight>",
    "upper_tag": "<INSIGHT>If a, then b.</INSIGHT>",
    "no_close": "<insight>If a, then b.",
    "empty_fenced_then_tag": "```insight\n```\n<insight>If a, then b.</insight>",
}
MERGE_REPLIES = {
    "two_lines": "```insights\nIf a, then b.\nIf c, then d.\n```",
    "numbered": "```insights\n1. If a, then b.\n- If c, then d.\n```",
    "indented": "```insights\n   If a, then b.\n```",
    "lower_if": "```insights\nif a, then b.\n```",
    "multiline_insight": "```insights\nIf a,\nthen b.\n```",
    "no_fence": "If a, then b.",
    "two_fences": "```insights\nIf a, then b.\n```\n```insights\nIf c, then d.\n```",
}
JUDGMENTS = {
    "sol2": "```judgment\nSolution 2 is better.\n```",
    "sol1": "```judgment\nSolution 1 is better.\n```",
    "sol2_lower": "```judgment\nsolution 2 is better\n```",
    "no_fence": "Solution 2 is better.",
    "sol1_mentions_sol2": "```judgment\nSolution 1 is better than solution 2.\n```",
}


def test_parsers():
    p = PARSERS
    assert {k: [list(x) for x in parse.subtasks(v)] for k, v in SUBTASKS.items()} == {k: v["ok"] for k, v in p["extract_subtasks"].items()}
    assert {k: parse.fenced(v, "insights") for k, v in FENCED.items()} == {k: v["ok"] for k, v in p["extract_fenced_blocks"].items()}
    first = {k: parse.first_fenced(v, "insights") for k, v in FENCED.items()}
    first["judgment"] = parse.first_fenced("```judgment\nSolution 2 is better.\n```", "judgment")
    assert first == {k: v["ok"] for k, v in p["extract_first_fenced_block"].items()}
    assert {k: MEM.condition(v) for k, v in CONDITIONS.items()} == {k: v["ok"] for k, v in p["extract_if_condition"].items()}
    assert {k: insight_of(v) for k, v in INSIGHT_REPLIES.items()} == {k: v["ok"] for k, v in p["EvoLibAgent.generate_insight"].items()}
    assert {k: MEM.merged_insights(v) for k, v in MERGE_REPLIES.items()} == {k: v["ok"] for k, v in p["EvoLibAgent.consolidate_insights"].items()}
    assert {k: second_better(v) for k, v in JUDGMENTS.items()} == {k: v["ok"] for k, v in p["EvoLibAgent.is_better_solution"].items()}

# память


def test_compute_ig():
    for case in MEMORY["compute_IG"].values():
        assert math.isclose(log_gain(case["best"], case["scores"]), case["IG"], abs_tol=1e-12)


def test_future_ig():
    """Шаги update_future_IG_for_* подряд на одной библиотеке; лучшая попытка — первая в выборке."""
    m = MEM.Library()
    ids = {"s1": m.skills.add("s1", ig=0.1).id, "s2": m.skills.add("s2", ig=0.1, outcomes=[0.3]).id,
           "i1": m.insights.add("i1").id, "i2": m.insights.add("i2", outcomes=[0.2]).id, "gone": "gone"}
    for case in MEMORY["update_future_IG"].values():
        shown = [[ids[x] for x in case["best_sample"]]] + [[ids[x] for x in s] for s in case["samples"][1:]]
        for rid, gain in future_gains(Attribution(shown, 0), case["scores"]):
            if m.get(rid):
                m.get(rid).outcomes.append(gain)
        assert {n: m.get(i).outcomes for n, i in ids.items() if n != "gone"} == case["after"]


SAMPLE_LIB = (
    [("skill_high", 0.7, [0.2, 0.4]), ("skill_negative_ig", -0.3, []), ("skill_zero", 0.0, [0.0])],
    [("If a, then b.", [0.5, 0.1]), ("If c, then d.", []), ("If e, then f.", [-1.0])],
)
SAMPLE_CASES = {"both": (1, 1, {}), "skills_only": (1, 0, {}), "insights_only": (0, 1, {}), "empty": (0, 0, {}),
                "w_IG_100": (1, 1, dict(w_ig=100.0)), "k_sample_2": (1, 1, dict(k=2))}


@pytest.mark.parametrize("case", list(SAMPLE_CASES))
def test_sample_from_library(monkeypatch, case):
    """Та же последовательность random: одно число на ветку, затем random.choices по весам."""
    skills, insights, kw = SAMPLE_CASES[case]
    m = MEM.Library()
    for text, ig, fig in SAMPLE_LIB[0] if skills else []:
        m.skills.add(text, ig=ig, outcomes=list(fig), doc="d")
    for text, fig in SAMPLE_LIB[1] if insights else []:
        m.insights.add(text, outcomes=list(fig))
    show, choices, log = SHOW.Sampler(**kw), random.choices, []
    monkeypatch.setattr(random, "choices", lambda pop, weights, k: log.append((pop, weights, k)) or choices(pop, weights, k=k))
    for run_ in MEMORY["sample_from_library"][case]:
        random.seed(run_["seed"])
        log.clear()
        p = show.prompt(Ex(None), m, {"context": "q"}, 0)
        texts = [m.get(i).text for i in p.shown]
        assert (texts if m.skills.get(p.shown[0] if p.shown else "") else []) == run_["skills"]
        assert (texts if m.insights.get(p.shown[0] if p.shown else "") else []) == run_["insights"]
        assert [([r.text for r in pop], pytest.approx(w), k) for pop, w, k in log] == \
               [(c["population"], c["weights"], c["k"]) for c in run_["choices"]]


INSIGHT_TABLE = [("base cond", [1.0, 0.0, 0.0]), ("near cond", [0.81, math.sqrt(1 - 0.81 ** 2), 0.0]),
                 ("far cond", [0.79, math.sqrt(1 - 0.79 ** 2), 0.0]), ("edge cond", [0.8, math.sqrt(1 - 0.8 ** 2), 0.0]),
                 ("merged cond", [0.95, math.sqrt(1 - 0.95 ** 2), 0.0]), ("other merged", [0.0, 1.0, 0.0])]
INSIGHT_REPLY = {
    "above_081_merge_to_one": "```insights\nIf merged cond, then do both.\n```",
    "above_081_merge_to_two": "```insights\nIf merged cond, then do one.\nIf other merged, then do two.\n```",
    "above_081_merge_to_zero": "no fenced block",
    "above_081_merge_keeps_old": "```insights\nIf base cond, then do x.\nIf near cond, then do y.\n```",
    "same_text_again": "```insights\nIf merged cond, then do both.\n```",
}


@pytest.mark.parametrize("case", list(MEMORY["add_new_insight"]))
def test_add_new_insight(monkeypatch, case):
    """Порог 0.8 строгий по условию insight; одна слитая запись наследует Future IG старой."""
    want = MEMORY["add_new_insight"][case]
    table_embed(monkeypatch, INSIGHT_TABLE)
    model = Fake([("merge", "consolidate these insights", INSIGHT_REPLY.get(case, ""))], default="")
    m = MEM.Library()
    m.add_insight(Ex(model), "If base cond, then do x.")
    m.insights.records()[0].outcomes.extend([0.4, 0.2])
    if want["new"]:                 # пустой insight извлечение в память не отдаёт (add_new_insight апстрима: return)
        m.add_insight(Ex(model), want["new"])
    assert state(m)[1] == upstream_state({}, figs(want["after"]))[1]
    assert [c["user"] for c in model.calls] == want["llm_prompts"]


def unit(cos):
    return [cos, math.sqrt(1 - cos * cos), 0.0]


SKILL_TABLE = [("Base desc", unit(1.0)), ("Near desc", unit(0.81)), ("Far desc", unit(0.79)), ("Merged desc", unit(0.97)),
               ("Split desc", [0.0, 1.0, 0.0])]
MERGED, SPLIT = solution("Merged desc.", "4", "4"), solution("Merged desc.", "4", "4") + "\n" + solution("Split desc.", "5", "5")
SKILL_REPLY = {"above_081_merge_to_one": MERGED, "above_081_merge_to_two": SPLIT, "above_081_merge_to_zero": "no subtasks",
               "batch_near_and_far": MERGED, "two_similar_in_one_batch": MERGED}


@pytest.mark.parametrize("case", list(MEMORY["add_new_skills"]))
def test_add_new_skills(monkeypatch, case):
    """Похожий skill (по description с тегами) сливается: IG — скользящее среднее с долей 0.5, Future IG старого."""
    want = MEMORY["add_new_skills"][case]
    table_embed(monkeypatch, SKILL_TABLE)
    model = Fake([("merge", "consolidate these example problems", SKILL_REPLY.get(case, ""))], default="")
    m = MEM.Library()
    m.add_skills(Ex(model), parse.subtasks(solution("Base desc.", "1", "1")), 0.9)
    m.skills.records()[0].outcomes.append(0.5)
    m.add_skills(Ex(model), [tuple(x) for x in want["new"]], want["IG_score"])
    got = [(t, [pytest.approx(ig), fig, doc]) for t, (ig, fig, doc) in state(m)[0]]
    assert got == upstream_state(want["after"], {})[0] and len(model.calls) == want["llm_calls"]

# run_iteration: баллы, IG, insight и деление, улучшение и сравнение решений


OK = "If sums are small, then do add digits."
ITERATION = {       # имя: (ответы попыток, ответ генерации insight, предыдущее лучшее решение, ответ сравнения)
    "2_of_3_insight": (["5", "5", "6"], f"<insight>{OK}</insight>", "", None),
    "2_of_3_insight_na": (["5", "5", "6"], "<insight>N/A</insight>", "", None),
    "all_differ": (["4", "5", "6"], f"<insight>{OK}</insight>", "", None),
    "dollar_stripped": (["$5$", "5", "6"], f"<insight>{OK}</insight>", "", None),
    "whitespace_differs": (["5", " 5 ", "5.0"], f"<insight>{OK}</insight>", "", None),
    "no_answer_tags": ([None, None, None], f"<insight>{OK}</insight>", "", None),
    "one_answer_only": (["5", None, None], f"<insight>{OK}</insight>", "", None),
    "prev_best_not_improving_judge_2": (["5", "5", "6"], "<insight>N/A</insight>", solution("Old.", "7", "7"),
                                        "```judgment\nSolution 2 is better.\n```"),
    "prev_best_not_improving_judge_1": (["5", "5", "6"], "<insight>N/A</insight>", solution("Old.", "7", "7"),
                                        "```judgment\nSolution 1 is better.\n```"),
    "prev_best_agrees_with_majority": (["5", "5", "6"], "<insight>N/A</insight>", solution("Old.", "5", "5"),
                                       "```judgment\nSolution 2 is better.\n```"),
    "gold_best_below_1": (["6", "7", "8"], f"<insight>{OK}</insight>", "", None),
    "gold_best_1": (["5", "6", "6"], f"<insight>{OK}</insight>", "", None),
}
UPSTREAM_RULE = {"majority": {"rule:0": "insight", "rule:1": "compare", "rule:2": "merge"},
                 "gold": {"rule:0": "insight"}}


@pytest.mark.parametrize("case", list(ITERATION))
def test_run_iteration(monkeypatch, case):
    """Попытки — готовые ответы эталона (решатель не зовётся); баллы, IG, insight, улучшение, библиотека и вызовы
    модели — как у run_iteration. Без эталона — голосование, с эталоном — вердикт попытки (ветка gold)."""
    want = MEMORY["run_iteration_majority_and_penalty"][case]
    answers, insight, prev, judge = ITERATION[case]
    gold = case.startswith("gold")
    table_embed(monkeypatch, [("Add numbers", unit(1.0))])
    sols = [solution(f"Add numbers variant {i}.", a, a) if a is not None else
            f"<subtask><description>Add numbers variant {i}.</description></subtask> no tags" for i, a in enumerate(answers)]
    eps = [Episode("Compute 2+3.", k, Prompt(), s, s, upstream_answer(s), [], False, [], [], []) for k, s in enumerate(sols)]
    g = Group("Compute 2+3.", eps)
    ex = Ex(Fake([("insight", "grain of salt, they might be wrong or incomplete. Try to spot", insight),
                  ("compare", "and two solutions", judge or ""), ("merge", "consolidate these", "no block")]))
    if gold:
        for e in eps:
            verdict.golden(ex, e, "5")
    else:
        verdict.vote(ex, g)
    m = MEM.Library()
    if prev:
        m.solutions[g.question] = Best(prev, upstream_answer(prev), 1.0)
    x = Gains(evaluated=gold)(ex, g, m)
    m.learn(ex, [x])
    r, b = want["result"], x.extras[ATTRIBUTION].best
    improving = m.best(g.question) is x.extras[BEST_ANSWER]
    assert (x.scores[b], eps[b].output, improving) == (r["best_score"], r["best_solution"], r["is_improving"])
    assert math.isclose(x.extras[IG], r["IG_score"]) and x.lessons == r["best_insights"]
    assert [blk for blk, _ in parse.subtasks(eps[b].output)] == r["best_skills"]
    assert state(m) == upstream_state(want["lib"]["skill_lib"], figs(want["lib"]["insight_lib"]))
    rules = UPSTREAM_RULE["gold" if gold else "majority"]
    assert [c["name"] for c in ex.model.calls] == [rules[c] for c in want["calls"] if c in rules]

# цикл


PROBLEMS = [
    ("Compute 12+30.", "42", [solution("Add two-digit numbers 12 and 30.", "42", "42"),
                              solution("Add two-digit numbers 12 and 30.", "42", "$42$"),
                              solution("Add two-digit numbers 12 and 30.", "41", "41")]),
    ("Compute 15+27.", "42", [solution("Add two-digit numbers 15 and 27 with carry.", "42", "42"),
                              solution("Add two-digit numbers 15 and 27 with carry.", "32", "32"),
                              solution("Add two-digit numbers 15 and 27 with carry.", "32", "32")]),
    ("Compute 6*7.", "42", [solution("Multiply single digits 6 and 7.", "42", "42")] * 3),
    ("Compute 84/2.", "42", [solution("Divide 84 by 2.", "42", "42"), solution("Divide 84 by 2.", "41", "41"),
                             solution("Divide 84 by 2.", "43", "43")]),
]
LOOP_TABLE = [("Add two-digit numbers 12", unit(1.0)), ("Add two-digit numbers 15", unit(0.9)),
              ("Add two-digit numbers", unit(0.95)), ("Multiply single digits", [0.0, 1.0, 0.0]), ("Divide", [0.0, 0.0, 1.0]),
              ("adding two-digit numbers", [0.6, 0.8, 0.0]), ("carrying", [0.6, 0.64, 0.48]), ("dividing", [0.0, 0.6, 0.8])]


def loop_model():
    spot = "Try to spot the mistakes"
    rules = [
        ("insight", lambda s, u: spot in u and "12+30" in u,
         "<mistake>m</mistake>\n<insight>\nIf adding two-digit numbers, then do add tens and units separately.\n</insight>"),
        ("insight", lambda s, u: spot in u and "15+27" in u,
         "```insight\nIf carrying a digit, then do not forget to add it to the next place.\n```"),
        ("insight", lambda s, u: spot in u and "6*7" in u, "<insight>\nN/A\n</insight>"),
        ("insight", lambda s, u: spot in u and "84/2" in u, "<insight>If dividing by 2, then do halve each digit.</insight>"),
        ("merge", "consolidate these insights",
         "```insights\nIf adding two-digit numbers or carrying, then do add tens and units and keep the carry.\n```"),
        ("merge", "consolidate these example problems", solution("Add two-digit numbers a and b.", "a+b", "a+b")),
        ("compare", "and two solutions", "```judgment\nSolution 1 is better.\n```"),
    ]
    rules += [("solver", lambda s, u, p=p: u.startswith(SOLVER_HEAD) and p in u, cycle(sols)) for p, _, sols in PROBLEMS]
    return Fake(rules)


@pytest.mark.parametrize("mode", ["nogold", "gold"])
def test_loop(monkeypatch, mode):
    """Два прохода по 4 задачам, как main() в eval_main.py: те же выборки из библиотеки (тот же поток random), та же
    библиотека, лучшие баллы и вызовы модели после каждой итерации."""
    table_embed(monkeypatch, LOOP_TABLE)
    task, model, snaps = Task([(p, a) for p, a, _ in PROBLEMS]), loop_model(), []
    learn = MEM.Library.learn

    def snapshot(self, ex, extractions):
        learn(self, ex, extractions)
        snaps.append((state(self), [self.best(p).score if self.best(p) else 0 for p, _, _ in PROBLEMS], len(model.calls)))
    monkeypatch.setattr(MEM.Library, "learn", snapshot)
    learner = E.evolib if mode == "nogold" else swap(E.evolib, "evolib_gold", extract=Gains(evaluated=True),
                                                    verdict=verdict.golden, group_verdict=verdict.none)
    run(task, swap(learner, protocol=Protocol(epochs=2)), model, n=len(PROBLEMS), split="train")     # с меткой — не по тесту
    want, start = LOOP[mode]["iterations"], 0
    assert len(snaps) == len(want)
    for (lib, best, end), it in zip(snaps, want):
        assert lib == upstream_state(it["lib"]["skills"], it["lib"]["insights"]), it["kiter"]
        assert best == [s for s, _ in it["best_scores"]], it["kiter"]
        up = [(c["messages"][0]["content"], {k: c[k] for k in REASONING}) for c in it["calls"]]
        ours = [(no_evaluation(c["user"]), c["params"]) for c in model.calls[start:end]]
        assert ours == up, it["kiter"]
        start = end
