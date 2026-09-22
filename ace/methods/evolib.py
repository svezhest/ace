"""EvoLib (EvoLib/EvoLib/evolib_agent.py, вариант HMMT из eval_main.py: без синтетических тестов).

    1 память      skills: подзадача целиком (<subtask> с description, solution, result), у неё скаляр IG
                  и список Future IG; insights «If ..., then ...» со списком Future IG
    2 инжект      у каждой попытки своя выборка с возвращением: p=0.4 до 10 skills, 0.3 до 10 insights,
                  0.3 ничего; вес skill = max(IG, eps) + (mean FIG или 0.5), insight = max(mean FIG или 0.5, eps)
    3 сигнал      без метки: попытка верна, если её ответ совпал с ответом большинства
    4 обновление  IG = log(лучший балл) - log(средний); из лучшего решения один insight, баллы при этом
                  делятся пополам; skills из ответа решателя идут в библиотеку, только если решение
                  задачи улучшилось; Future IG всем записям выборки лучшей попытки;
                  похожее (косинус > 0.8 по условию insight или description skill) сливает LLM
    решатель      3 попытки при T=0, в зачёт ответ большинства; решение разбито на подзадачи

Промпты апстрима, из них убрано только «math»: у нас не только математика.
Эпох в апстриме тысячи (5000 итераций по кругу), у нас это параметр протокола EPOCHS.
"""
import math
import random

from .. import embed
from ..feedback import Feedback
from ..inject import View
from ..loop import Method, Solver, swap
from ..update import Update

# 1. память

MEMORY = {"skill": ("add", "delete"), "insight": ("add", "delete")}   # delete только при слиянии

# 2. инжект

K, W_IG, EPS = 10, 1.0, 0.01

SKILLS = "Here are some subtask solutions which you may reuse or adapt for the problem:\n"
INSIGHTS = "Here are some insights that may help you solve the problem:\n"


def weight(r):
    fig = r.meta["fig"]
    future = sum(fig) / len(fig) if fig else 0.5
    if r.kind == "skill":
        return W_IG * max(r.meta["ig"], EPS) + future
    return max(future, EPS)


def sample(model, memory, item):
    skills, insights, p = memory.of("skill"), memory.of("insight"), random.random()
    if skills and p < 0.4:
        head, pool = SKILLS, skills
    elif insights and p < 0.7:
        head, pool = INSIGHTS, insights
    else:
        return View()
    # в апстриме пола нет: отрицательный вес skill ломает random.choices молча
    picked = random.choices(pool, [max(weight(r), EPS) for r in pool], k=min(len(pool), K))
    return View(head + "\n".join(r.text for r in picked), [r.id for r in picked], head="")

# 4. обновление

INSIGHT = """You are an expert. You are given the following problem and a potential solution:
Problem: {question}

Take the following solution with a grain of salt, they might be wrong or incomplete. Try to spot the mistakes in the solution if any to get a more accurate solution.
{solution}
{evaluation}
Output format (Use exact <...> tags in the following format):
<mistake>
If you can identify a mistake in the above reference solution and think of a more accurate one, explain here in a stand-alone manner, you must explain what is the reference solution's final answer, and why is it incorrect. (or write "N/A" if you agree with the reference solution)
</mistake>
<improved_solution>
A paragraph of detailed step-by-step summary of your solution, write thoroughly and in details, note down every steps of calculation you did, and what was the final answer you got. (or write "N/A" if you agree with the reference solution)
</improved_solution>
<insight>
Based on the above mistake identified in the reference solution and the improved solution, write a SINGLE insight in the pseudo-code format of "If (certain situation), then do (what to do)" or "If (certain situation), then do not (what to avoid)" or "If (certain situation), then consider the case (the cases to consider)".
The insight should be specific enough to help fix the mistake AND also understandable without the context of the specific problem, so that it can be applied to future problems with similar situations.
(or write "N/A" if you agree with the reference solution)
</insight>
"""

MERGE_SKILLS = """You are an expert. Your task is to help students consolidate example problems and solutions into fewer, more generalizable ones to help them solve future problems.
Here are the example problems and solutions:
{skills}

Please consolidate these example problems and solutions by merging the ones that solve (almost) identical tasks into a single one that can be referenced for solving future problems.
If there are example problems that solve different tasks or the same tasks but with different goals, please keep them as separate examples.
If there are example problems with identical tasks and similar solution approaches, merge them into a single example by keeping the most accurate parts of the solutions.
NOTE: Please preserve the original logic and reasoning of the solutions, and do not change any existing solution logic unless it is incorrect.
Output the consolidated example problems and solutions in the same format as the input.
"""

MERGE_INSIGHTS = """You are an expert that helps consolidate insights for better problem solving.
Here are some insights generated from previous problems:
```insights
{insights}
```
Please consolidate these insights by merging the ones with similar conditioning situations into a single insight.
If there are insights with distinct conditioning situations, please do not merge them together.
If there are insights with similar conditioning situations, merge them into a single insight by keeping the common conditioning situation and adding the different action parts together.
NOTE: Please preserve the original meaning of the insights, and do not change any existing insight logic.
The consolidated insights should follow the pseudo-code format of "If (certain situation), then do (what to do)" or "If (certain situation), then do not (what to avoid)" or "If (certain situation), then consider the case (the cases to consider)".
Put the consolidated insights within ```insights and ```.
"""

COMPARE = """You are an expert. You are given the following problem and two solutions:
Problem: {question}

Take the following solutions with a grain of salt, they might be wrong or incomplete.
Your task is to judge which solution is more likely to be correct.

Solution 1:
{a}

Solution 2:
{b}

First, check each step in solution 1, and list the mistakes made in it, if there is any.
Next, check each step in solution 2, and list the mistakes made in it, if there is any.
Finally, make a final judgment of which solution is more likely to be correct in the format:
```judgment
Solution <id (1 or 2)> is better.
```
"""

SIM, RATE = 0.8, 0.5


def between(text, start, end):
    if start not in text or end not in text.split(start, 1)[1]:
        return ""
    return text.split(start, 1)[1].split(end, 1)[0].strip()


def fenced(text, tag):
    """Содержимое всех блоков ```tag ... ``` подряд."""
    return "\n".join(part.split("```")[0] for part in text.split("```" + tag)[1:])


def subtasks(text):
    """Пары (блок <subtask> целиком, его description); без description извлечение не удаётся целиком."""
    out = []
    for chunk in text.split("<subtask>")[1:]:
        if "</subtask>" not in chunk:
            continue
        block = chunk.split("</subtask>")[0]
        if not between(block, "<description>", "</description>"):
            return []
        out.append((f"<subtask>{block}</subtask>", between(block, "<description>", "</description>")))
    return out


def condition(insight):
    return insight.split(", then ")[0].replace("If ", "").strip()


def ask(model, prompt):
    return model.one("", prompt).output or ""


def reflect(evaluated=False):
    """evaluated: баллы попыток дала внешняя оценка (метка или судья), как синтетические тесты
    в кодовых задачах апстрима: тогда insight только при неудаче лучшей попытки и без деления баллов."""
    def run(ctx, ep, memory):
        attempts = [ep, *ep.group]
        scores = [float(bool(a.ok)) for a in attempts]
        b = max(range(len(attempts)), key=scores.__getitem__)      # первая из лучших
        best = attempts[b]
        ig = math.log(max(scores[b], EPS)) - math.log(max(sum(scores) / len(scores), EPS))
        insight = ""
        if not evaluated or scores[b] < 1:
            text = ask(ctx.model, INSIGHT.format(question=ep.question, solution=best.output,
                                                 evaluation=f"\nEvaluation: {best.verdict()}\n" if evaluated else ""))
            insight = fenced(text, "insight").strip() or between(text, "<insight>", "</insight>")
            insight = "" if insight == "N/A" else insight
            if insight and not evaluated:
                scores = [s * 0.5 for s in scores]
        prev = ctx.state.setdefault("best", {}).get(ep.question)
        improving = not prev or scores[b] > prev["score"]
        voted = best.answer if best.ok and not evaluated else None
        if not improving and voted and prev["answer"] != voted:
            improving = "solution 2" in fenced(ask(ctx.model, COMPARE.format(
                question=ep.question, a=prev["output"], b=best.output)), "judgment").lower()
        fig = []
        for rid in best.shown:                                     # с повторами, как в апстриме
            rest = [s for s, a in zip(scores, attempts) if rid not in a.shown]
            if rest:
                fig.append((rid, math.log(max(scores[b], EPS)) - math.log(max(sum(rest) / len(rest), EPS))))
        return dict(question=ep.question, ig=ig, insight=insight, fig=fig,
                    skills=subtasks(best.output) if improving else [],
                    best=dict(score=scores[b], output=best.output, answer=best.answer) if improving else None)
    return run


def curate(ctx, memory, deltas):
    for d in deltas:
        if d["insight"]:
            add_insight(ctx.model, memory, d["insight"])
        if d["best"]:
            ctx.state["best"][d["question"]] = d["best"]
        for block, doc in d["skills"]:
            add_skill(ctx.model, memory, block, doc, d["ig"])
        for rid, v in d["fig"]:
            if memory.get(rid):
                memory.get(rid).meta["fig"].append(v)


def nearest(records, text, key):
    """Записи с косинусом строго больше SIM, от самой близкой."""
    if not records:
        return []
    sims = embed.embed([key(r) for r in records]) @ embed.embed([text])[0]
    return [records[i] for i in sims.argsort()[::-1] if sims[i] > SIM]


def add_insight(model, memory, text):
    near = nearest(memory.of("insight"), condition(text), lambda r: condition(r.text))
    if not near:
        memory.add(text, "insight", meta={"fig": []})
        return
    old = near[0]
    merged = [l.strip() for l in fenced(ask(model, MERGE_INSIGHTS.format(insights=f"{old.text}\n{text}")), "insights").splitlines()
              if l.strip().startswith("If ")]
    fig = old.meta["fig"] if len(merged) == 1 else []
    if len(merged) == 1:
        memory.drop(old.id)
    for t in merged:
        if t not in {r.text for r in memory.of("insight")}:
            memory.add(t, "insight", meta={"fig": fig})


def add_skill(model, memory, block, doc, ig):
    near = nearest(memory.of("skill"), doc, lambda r: r.meta["doc"])
    if not near:
        memory.add(block, "skill", meta=dict(ig=ig, fig=[], doc=doc))
        return
    old = near[0]
    merged = subtasks(ask(model, MERGE_SKILLS.format(skills=f"{old.text}\n{block}")))
    fig = []
    if len(merged) == 1:
        ig, fig = RATE * ig + (1 - RATE) * old.meta["ig"], old.meta["fig"]
        memory.drop(old.id)
    for b, d in merged:
        if b not in {r.text for r in memory.of("skill")}:
            memory.add(b, "skill", meta=dict(ig=ig, fig=fig, doc=d))

# решатель

SUBTASKS = """

Plan ahead how to break down the problem into several subtasks, then write down the solution.
The solution should consist of several blocks, where each block represents a subtask:
<subtask>
<description>
Description of the subtask, constraints or conditions and input variable assignment.
NOTE: the description should be understandable and solvable on its own without the context of the original problem or reference to the other subtasks, so that it can be reused for future problems with similar subtasks.
</description>
<solution>
Solution and computation steps of the subtask.
</solution>
<result>...</result>
</subtask>
The final block should be the aggregation step that takes the intermediate results from the previous blocks and deduces the final answer."""

evolib = Method("evolib", MEMORY, sample, Feedback("majority"), Update(reflect(), curate),
                Solver(samples=2, temperature=0, vote=True, hint=SUBTASKS))
evolib_judge = swap(evolib, "evolib_judge", feedback=Feedback("judge"), reflect=reflect(evaluated=True))
