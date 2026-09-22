"""EvoLib: библиотека из skills (подзадача с решением) и insights (урок). Без меток: лучшая из K
попыток выбирается самооценкой. Из лучшей извлекаются новые абстракции. Вес записи
w = tau * max IG + mean Future IG (tau = 1 для skill, 0 для insight); по весу сэмплируется
контекст. Похожие по эмбеддингу записи (>= 0.8) консолидируются, явного удаления нет."""
import random
from typing import Literal

from pydantic import BaseModel

from .. import embed
from ..loop import Method

SCORE = """Rate how likely this solution is fully correct, from 0 to 1. Reply with the number only.

## Task
{question}

## Solution
{output}"""

EXTRACT = """From the solution below extract reusable abstractions for future tasks of this family:
skills = a sub-task together with how it was solved; insights = a lesson about a mistake or a fix.
At most 2 of each, each under 40 words.

## Task
{question}

## Best solution
{output}

## Other attempts
{others}"""

SAME = """Do these two entries express the same abstraction? Answer yes or no.

1. {a}
2. {b}"""

M, SIM = 10, 0.8      # по M записей каждого типа в контекст; порог консолидации


class Item(BaseModel):
    kind: Literal["skill", "insight"]
    text: str


class Items(BaseModel):
    items: list[Item] = []


def weight(r):
    tau = 1.0 if r.kind == "skill" else 0.0
    ig, fig = r.meta.setdefault("ig", []), r.meta.setdefault("fig", [])
    return tau * max(ig, default=0) + (sum(fig) / len(fig) if fig else 0)


def inject(memory):
    picked = []
    for kind in ("skill", "insight"):
        pool = [r for r in memory.records if r.kind == kind]
        for _ in range(min(M, len(pool))):
            ws = [max(weight(r), 0) + 0.05 for r in pool]      # небольшой пол, чтобы новые тоже пробовались
            r = random.choices(pool, ws)[0]
            pool.remove(r)
            picked.append(r)
    memory.used = [r.id for r in picked]
    return "\n".join(f"[{r.id}] ({r.kind}) {r.text}" for r in picked)


def score(model, trace):
    s = model.one("You are a strict grader.", SCORE.format(question=trace.question, output=trace.output)).output or "0"
    try:
        return float(s.strip().split()[0])
    except ValueError:
        return 0.0


def reflect(model, trace, memory):
    attempts = [trace] + trace.group
    scores = {id(t): score(model, t) for t in attempts}
    best = max(attempts, key=lambda t: scores[id(t)])
    # IG для сэмплированных записей: средний скор попыток с записью минус без неё
    for rid in {i for t in attempts for i in t.used}:
        rec = memory.get(rid)
        w = [scores[id(t)] for t in attempts if rid in t.used]
        wo = [scores[id(t)] for t in attempts if rid not in t.used]
        if rec and w and wo:
            rec.meta.setdefault("ig", []).append(sum(w) / len(w) - sum(wo) / len(wo))
    others = "\n\n".join(t.output for t in attempts if t is not best) or "(none)"
    r = model.run("You are an extractor.", EXTRACT.format(question=trace.question, output=best.output, others=others), output=Items).output
    items = r.items if r else []
    # IG новой абстракции: скор лучшей минус средний скор попыток (без неё)
    gain = scores[id(best)] - sum(scores.values()) / len(scores)
    # Future IG: записи в контексте лучшей попытки способствовали появлению новых
    for rid in best.used:
        if memory.get(rid):
            memory.get(rid).meta.setdefault("fig", []).append(gain if items else 0)
    return [(it, gain) for it in items] or None


def curate(model, memory, items):
    for it, gain in items:
        same = [r for r in memory.records if r.kind == it.kind]
        near = None
        if same:
            sims = embed.embed([it.text])[0] @ embed.embed([r.text for r in same]).T
            j = int(sims.argmax())
            if sims[j] >= SIM and (model.one("You compare entries.", SAME.format(a=it.text, b=same[j].text)).output or "").lower().startswith("y"):
                near = same[j]
        if near:
            near.meta.setdefault("ig", []).append(gain)
        else:
            memory.add(it.text, kind=it.kind, meta={"ig": [gain], "fig": []})


evolib = Method("evolib", inject=inject, reflect=reflect, curate=curate, group=2, signal="self")
