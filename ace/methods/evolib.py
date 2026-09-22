"""EvoLib.

    1 память      skills (подзадача с решением) и insights (урок); удаления нет;
                  у записи история IG и Future IG
    2 инжект      по M записей каждого вида, сэмплированных по весу w = tau * max IG + mean FIG
                  (tau = 1 для skill, 0 для insight); у каждой попытки своя выборка
    3 сигнал      без метки: вердикт каждой попытке ставит сама модель
    4 обновление  IG записей, бывших в промпте: средний вердикт попыток с записью минус без неё;
                  из лучшей попытки извлекаются новые абстракции; похожие по эмбеддингу (>= 0.8)
                  и подтверждённые моделью консолидируются
    решатель      1 + 2 попытки на вопрос
"""
import random
from typing import Literal

from pydantic import BaseModel

from .. import embed
from ..feedback import Feedback
from ..inject import View
from ..loop import Method, Solver
from ..update import Update

# 1. память

MEMORY = {"skill": ("add",), "insight": ("add",)}

# 2. инжект

M = 10


def weight(r):
    tau = 1.0 if r.kind == "skill" else 0.0
    ig, fig = r.meta.get("ig", []), r.meta.get("fig", [])
    return tau * max(ig, default=0) + (sum(fig) / len(fig) if fig else 0)


def sample(model, memory, item):
    picked = []
    for kind in ("skill", "insight"):
        pool = memory.of(kind)
        for _ in range(min(M, len(pool))):
            ws = [max(weight(r), 0) + 0.05 for r in pool]      # небольшой пол, чтобы новые тоже пробовались
            r = random.choices(pool, ws)[0]
            pool.remove(r)
            picked.append(r)
    return View("\n".join(f"[{r.id}] ({r.kind}) {r.text}" for r in picked), [r.id for r in picked])

# 4. обновление

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

SIM = 0.8


class Item(BaseModel):
    kind: Literal["skill", "insight"]
    text: str


class Items(BaseModel):
    items: list[Item] = []


def reflect(ctx, ep, memory):
    attempts = [ep] + ep.group
    score = lambda a: float(bool(a.ok))
    best = max(attempts, key=score)
    mean = sum(map(score, attempts)) / len(attempts)
    # IG записи: средний вердикт попыток, где она была в промпте, минус где не было
    ig = {}
    for rid in {i for a in attempts for i in a.shown}:
        w = [score(a) for a in attempts if rid in a.shown]
        wo = [score(a) for a in attempts if rid not in a.shown]
        if w and wo:
            ig[rid] = sum(w) / len(w) - sum(wo) / len(wo)
    others = "\n\n".join(a.output for a in attempts if a is not best) or "(none)"
    r = ctx.model.run("You are an extractor.", EXTRACT.format(question=ep.question, output=best.output, others=others), output=Items).output
    items = r.items if r else []
    gain = score(best) - mean                          # IG новой абстракции: лучшая попытка против средней
    return dict(ig=ig, fig={rid: gain if items else 0 for rid in best.shown}, items=items, gain=gain)


def curate(ctx, memory, deltas):
    for d in deltas:
        for rid, v in d["ig"].items():
            if memory.get(rid):
                memory.get(rid).meta.setdefault("ig", []).append(v)
        # Future IG: записи в промпте лучшей попытки способствовали появлению новых
        for rid, v in d["fig"].items():
            if memory.get(rid):
                memory.get(rid).meta.setdefault("fig", []).append(v)
        for it in d["items"]:
            near = similar(ctx.model, memory, it)
            if near:
                near.meta.setdefault("ig", []).append(d["gain"])
            else:
                memory.add(it.text, kind=it.kind, meta={"ig": [d["gain"]], "fig": []})


def similar(model, memory, it):
    same = memory.of(it.kind)
    if not same:
        return None
    sims = embed.embed([it.text])[0] @ embed.embed([r.text for r in same]).T
    j = int(sims.argmax())
    if sims[j] >= SIM and (model.one("You compare entries.", SAME.format(a=it.text, b=same[j].text)).output or "").lower().startswith("y"):
        return same[j]
    return None


evolib = Method("evolib", MEMORY, sample, Feedback("judge"), Update(reflect, curate), Solver(samples=2))
