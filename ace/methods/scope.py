"""SCOPE: правила по шагам траектории, два потока (tactical / strategic) по уверенности,
синтез Best-of-N с выбором, оптимизация памяти при переполнении, K перспектив при решении."""
from dataclasses import replace
from typing import Literal

from pydantic import BaseModel

from ..loop import Method, solve

JUDGE = """Look at one step of an agent solving a task and decide whether it needs a guideline.
"corrective": the step contains an error whose fix is visible in the step itself.
"enhancement": no error, but the strategy is clearly suboptimal.
"none": nothing to learn.

## Task
{question}

## Step
{step}

## Outcome of the whole attempt
{outcome}"""

SYNTH = """Write one guideline (under 60 words) that would improve this step next time.
Give a confidence from 0 to 1 that the guideline holds for the whole task family, not just this input.

## Task
{question}

## Step
{step}

## Why it needs a guideline
{why}

## Existing guidelines
{memory}"""

SELECT = """Two candidate guidelines for the same step. Pick the more specific and actionable one: answer 1 or 2.

## Step
{step}

## 1
{a}

## 2
{b}"""

OPTIMIZE = """These guidelines have grown past the limit. Return at most {target} of them:
drop the ones that conflict with a better one, drop the ones subsumed by a more general one,
and merge near-duplicates into one. Do not invent new rules.

{rules}"""

CAP, TARGET, N, STRATEGIC = 10, 8, 2, 0.85
PERSPECTIVES = ("Perspective: efficiency. Prefer the shortest reliable path.",
                "Perspective: thoroughness. Check every intermediate quantity.")


class Verdict(BaseModel):
    kind: Literal["corrective", "enhancement", "none"]
    why: str = ""


class Guideline(BaseModel):
    text: str
    confidence: float


class Rules(BaseModel):
    rules: list[str]


def steps_of(trace):
    """Шаги = вызовы tools; без tools вся траектория — один шаг."""
    return [f"[{name}] {args}\n-> {result}" for name, args, result in trace.steps] or [trace.output]


def reflect(model, trace, memory):
    outcome = "correct" if trace.correct else f"wrong, expected {trace.target}"
    if trace.truncated:
        outcome = "output truncated"
    found = []
    for step in steps_of(trace):
        v = model.run("You are a judge.", JUDGE.format(question=trace.question, step=step, outcome=outcome), output=Verdict).output
        if not v or v.kind == "none":
            continue
        prompt = SYNTH.format(question=trace.question, step=step, why=f"{v.kind}: {v.why}", memory=inject(memory))
        cands = [model.run("You are a guideline synthesizer.", prompt, output=Guideline, temperature=0.7).output for _ in range(N)]
        cands = [c for c in cands if c]
        if len(cands) == N:
            pick = model.one("You are a selector.", SELECT.format(step=step, a=cands[0].text, b=cands[1].text)).output or "1"
            cands = [cands[1] if pick.strip().startswith("2") else cands[0]]
        found += cands
    return found or None


def curate(model, memory, guidelines):
    for g in guidelines:
        stream = "strategic" if g.confidence >= STRATEGIC else "tactical"
        if g.text not in {x.text for x in memory.records}:
            memory.add(g.text, kind=stream)


def bound(model, memory, *_):
    for stream in ("tactical", "strategic"):
        for _ in range(2):                               # не больше двух проходов
            same = [x for x in memory.records if x.kind == stream]
            if len(same) <= CAP:
                break
            r = model.run("You are a memory optimizer.", OPTIMIZE.format(
                target=TARGET, rules="\n".join(f"- {x.text}" for x in same)), output=Rules).output
            if not r:
                break
            for x in same:
                memory.drop(x.id)
            for text in r.rules[:CAP]:
                memory.add(text, kind=stream)


def inject(memory):
    lines = lambda kind: "\n".join(f"- {r.text}" for r in memory.records if r.kind == kind) or "(none)"
    return f"Strategic guidelines:\n{lines('strategic')}\n\nTactical guidelines:\n{lines('tactical')}"


scope = Method("scope", inject=inject, reflect=reflect, curate=curate, bound=bound)
# K=2 перспектив, засчитывается лучшая из двух попыток (max по оценке, как в статье)
scope_k2 = replace(scope, name="scope_k2", perspectives=PERSPECTIVES)
