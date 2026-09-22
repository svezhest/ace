"""EvoLib (EvoLib/EvoLib/evolib_agent.py, вариант HMMT из eval_main.py: без синтетических тестов).
Промпты prompts/evolib_*.txt: апстрим, из которого убрано только «math».

    1 память      skills: подзадача целиком (<subtask> с description, solution, result), в meta скаляр ig,
                  список fig и doc; insights «If ..., then ...», в meta список fig
    2 инжект      choose: одно случайное число на попытку — p < 0.4 sample до 10 skills, p < 0.7 до 10 insights,
                  иначе ничего; выборка с возвращением по весу
    3 сигнал      без метки: попытка верна, если её ответ совпал с ответом большинства
    4 обновление  reflect: seq(ранжирование и IG = log_gain, maybe(insight из лучшего решения; баллы пополам),
                  улучшение по задаче, maybe(сравнение двух решений моделью), skills из ответа, future_gain);
                  curate: consolidate insight и skills (косинус > 0.8 по условию или description, слияние моделью),
                  лучшее решение задачи в ctx.state, Future IG в записи
    решатель      3 попытки при T=0, в зачёт ответ большинства; решение разбито на подзадачи (Solver.hint)

Эпох в апстриме тысячи (5000 итераций по кругу), у нас это параметр протокола EPOCHS.
"""

from .. import curate as stages, inject, prompts
from ..feedback import Feedback
from ..loop import Method, Solver, swap
from ..reflect import future_gain, log_gain
from ..update import Delta, Update, ask, maybe, seq

P = {n: prompts.load(f"evolib_{n}.txt") for n in ("insight", "merge_skills", "merge_insights", "compare")}

# 1. память

MEMORY = {"skill": ("add", "delete"), "insight": ("add", "delete")}   # delete только при слиянии

# 2. инжект

K, W_IG, EPS = 10, 1.0, 0.01


def weight(r):
    """w_IG * max(IG, eps) + (mean FIG или 0.5) у skill, max(mean FIG или 0.5, eps) у insight.
    В апстриме у skill пола нет: отрицательный вес ломает random.choices молча, поэтому здесь пол eps."""
    fig = r.meta["fig"]
    future = sum(fig) / len(fig) if fig else 0.5
    if r.kind == "skill":
        return max(W_IG * max(r.meta["ig"], EPS) + future, EPS)
    return max(future, EPS)


def library(kind, head):
    return inject.show((kind,), pick=inject.sample(K, weight), line=inject.plain, before=head, head="")


sample = inject.choose(
    (0.4, library("skill", "Here are some subtask solutions which you may reuse or adapt for the problem:\n")),
    (0.7, library("insight", "Here are some insights that may help you solve the problem:\n")))

# 4. обновление

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


def rank(ctx, ep, memory, **extra):
    attempts = [ep, *ep.group]
    scores = [float(bool(a.ok)) for a in attempts]
    b = max(range(len(attempts)), key=scores.__getitem__)          # первая из лучших
    return dict(attempts=attempts, scores=scores, b=b, ig=log_gain(scores[b], scores, EPS), insight="")


def with_insight(evaluated):
    def then(text, ctx, ep, memory, prev, **extra):
        insight = fenced(text or "", "insight").strip() or between(text or "", "<insight>", "</insight>")
        insight = "" if insight == "N/A" else insight
        halve = insight and not evaluated                         # без внешней оценки баллы делятся пополам
        return dict(prev, insight=insight, scores=[s * 0.5 for s in prev["scores"]] if halve else prev["scores"])
    return then


def improving(ctx, ep, memory, prev, **extra):
    before = ctx.state.setdefault("best", {}).get(ep.question)
    return dict(prev, before=before, improving=not before or prev["scores"][prev["b"]] > before["score"])


def disputed(evaluated):
    """Не лучше по баллу, но большинство теперь за другой ответ: решает сравнение решений моделью."""
    def test(ctx, ep, memory, prev, **extra):
        best = prev["attempts"][prev["b"]]
        voted = best.answer if best.ok and not evaluated else None
        return not prev["improving"] and voted and prev["before"]["answer"] != voted
    return test


def finish(ctx, ep, memory, prev, **extra):
    attempts, scores, b = prev["attempts"], prev["scores"], prev["b"]
    best, up = attempts[b], prev["improving"]
    return Delta(info=dict(question=ep.question, ig=prev["ig"], insight=prev["insight"], fig=future_gain(attempts, scores, b, EPS),
                           skills=subtasks(best.output) if up else [],
                           best=dict(score=scores[b], output=best.output, answer=best.answer) if up else None))


def reflect(evaluated=False):
    """evaluated: баллы попыток дала внешняя оценка (метка или судья), как синтетические тесты
    в кодовых задачах апстрима: тогда insight только при неудаче лучшей попытки и без деления баллов."""
    insight = ask(P["insight"], lambda ctx, ep, memory, prev, **_: dict(
        question=ep.question, solution=prev["attempts"][prev["b"]].output,
        evaluation=f"\nEvaluation: {prev['attempts'][prev['b']].verdict()}\n" if evaluated else ""), then=with_insight(evaluated))
    compare = ask(P["compare"], lambda ctx, ep, memory, prev, **_: dict(
        question=ep.question, a=prev["before"]["output"], b=prev["attempts"][prev["b"]].output),
        then=lambda text, ctx, ep, memory, prev, **_: dict(prev, improving="solution 2" in fenced(text or "", "judgment").lower()))
    return seq(rank, maybe(lambda ctx, ep, memory, prev, **_: not evaluated or prev["scores"][prev["b"]] < 1, insight),
               improving, maybe(disputed(evaluated), compare), finish)


def merge_insights(ctx, old, text):
    out = ctx.model.one("", P["merge_insights"].fill(dict(insights=f"{old.text}\n{text}"))).output or ""
    fig = []                                                        # общий список, как в апстриме
    return [(l.strip(), {"fig": fig}) for l in fenced(out, "insights").splitlines() if l.strip().startswith("If ")]


def merge_skills(ig):
    def merge(ctx, old, block):
        out = ctx.model.one("", P["merge_skills"].fill(dict(skills=f"{old.text}\n{block}"))).output or ""
        fig = []
        return [(b, dict(ig=ig, fig=fig, doc=d)) for b, d in subtasks(out)]
    return merge


add_insight = stages.consolidate("insight", lambda text, meta: condition(text), SIM, merge_insights,
                                 inherit=lambda old, meta: {"fig": old.meta["fig"]})


def add_skill(ig):
    return stages.consolidate("skill", lambda text, meta: meta["doc"], SIM, merge_skills(ig),
                              inherit=lambda old, meta: dict(meta, ig=RATE * meta["ig"] + (1 - RATE) * old.meta["ig"], fig=old.meta["fig"]))


def curate_one(ctx, memory, d):
    d = d.info
    if d["insight"]:
        add_insight(ctx, memory, d["insight"], {"fig": []})
    if d["best"]:
        ctx.state["best"][d["question"]] = d["best"]
    for block, doc in d["skills"]:
        add_skill(d["ig"])(ctx, memory, block, dict(ig=d["ig"], fig=[], doc=doc))
    for rid, v in d["fig"]:
        if memory.get(rid):
            memory.get(rid).meta["fig"].append(v)


curate = stages.each(curate_one)

# решатель

SUBTASKS = prompts.load("evolib_subtasks.txt").text

evolib = Method("evolib", MEMORY, sample, Feedback("majority"), Update(reflect(), curate),
                Solver(samples=2, temperature=0, vote=True, hint=SUBTASKS))
evolib_judge = swap(evolib, "evolib_judge", feedback=Feedback("judge"), reflect=reflect(evaluated=True))
