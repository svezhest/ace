"""SCOPE: два потока правил. Тактические пишутся по каждой ошибке, стратегические — обобщения,
которые синтезатор выделяет с высокой уверенностью. Оба потока ограничены по размеру."""
from typing import Literal

from pydantic import BaseModel

from ..loop import Method

SYNTH = """The agent failed a task. Write one rule that would prevent this class of mistake next time.
"tactical" = specific to this kind of input; "strategic" = general principle for the whole task family.

## Task
{question}

## Output
{output}

## Error
{error}

## Existing rules
{memory}"""

CAP = 10


class Rule(BaseModel):
    rule: str
    scope: Literal["tactical", "strategic"]
    confidence: float


def reflect(model, trace, memory):
    if trace.correct:
        return None
    error = f"wrong answer, expected {trace.target}" if not trace.truncated else "output truncated"
    return model.run("You are a rule synthesizer.", SYNTH.format(
        question=trace.question, output=trace.output, error=error, memory=memory.text() or "(empty)"), output=Rule).output


def curate(model, memory, r):
    kind = "strategic" if r.scope == "strategic" and r.confidence >= 0.7 else "tactical"
    if r.rule not in {x.text for x in memory.records}:
        memory.add(r.rule, kind=kind)


def bound(model, memory, *_):
    for kind in ("tactical", "strategic"):
        same = [x for x in memory.records if x.kind == kind]
        for x in same[:-CAP]:
            memory.drop(x.id)


def inject(memory):
    lines = lambda kind: "\n".join(f"- {r.text}" for r in memory.records if r.kind == kind) or "(none)"
    return f"Strategic rules:\n{lines('strategic')}\n\nTactical rules:\n{lines('tactical')}"


scope = Method("scope", inject=inject, reflect=reflect, curate=curate, bound=bound)
