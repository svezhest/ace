"""EvoLib: память как популяция. Каждая попытка получает случайную подвыборку записей,
записи накапливают успехи и провалы, слабые отбраковываются, инсайты рождаются на неудачах."""
import random

from pydantic import BaseModel

from ..loop import Method

INSIGHT = """The attempts below failed. Write 1-2 short insights that would have led to the correct answer.

## Task
{question}

## Correct answer
{target}

## Attempts
{attempts}"""

class Insights(BaseModel):
    insights: list[str]


SAMPLE, MIN_USES, MIN_RATE, CAP = 5, 4, 0.3, 30


def inject(memory):
    picked = random.sample(memory.records, min(SAMPLE, len(memory.records)))
    memory.used = [r.id for r in picked]
    return "\n".join(f"[{r.id}] {r.text}" for r in picked)


def reflect(model, trace, memory):
    attempts = [trace] + trace.group
    for t in attempts:
        for id in t.used:
            rec = memory.get(id)
            if rec:
                rec.helpful += t.correct
                rec.harmful += not t.correct
    if any(t.correct for t in attempts):
        return None
    r = model.run("You are a reflector.", INSIGHT.format(
        question=trace.question, target=trace.target, attempts="\n\n".join(t.output for t in attempts)),
        output=Insights).output
    return r.insights if r and r.insights else None


def curate(model, memory, insights):
    for text in insights:
        memory.add(text)


def bound(model, memory, *_):
    fit = lambda r: r.helpful / (r.helpful + r.harmful or 1)
    for r in list(memory.records):
        if r.helpful + r.harmful >= MIN_USES and fit(r) < MIN_RATE:
            memory.drop(r.id)
    memory.records = sorted(memory.records, key=fit, reverse=True)[:CAP]


evolib = Method("evolib", inject=inject, reflect=reflect, curate=curate, bound=bound, group=2)
