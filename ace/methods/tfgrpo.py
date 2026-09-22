"""Training-Free GRPO. Две стадии: по группе из G попыток модель пишет, чем верные отличались
от неверных (семантическое преимущество); раз в батч такие тексты сводятся в библиотеку
опытов операциями Add / Modify / Delete / Keep. Опыт — до 32 слов."""
from typing import Literal

from pydantic import BaseModel

from ..loop import Method

ADVANTAGE = """Below are several attempts at the same task; some are correct, some are not.
Write what the correct ones did that the wrong ones did not, in one or two sentences.

## Task
{question}

## Correct answer
{target}

{attempts}"""

CONSOLIDATE = """You maintain a library of experiences (each under 32 words) for a task family.
Given the new group summaries, update the library with a few operations:
add a new experience, modify an existing one by id, delete one by id, or keep everything.

## Library
{memory}

## Group summaries from the last batch
{summaries}"""

WORDS, BATCH = 32, 5


class Op(BaseModel):
    op: Literal["add", "modify", "delete", "keep"]
    id: str = ""
    text: str = ""


class Ops(BaseModel):
    ops: list[Op] = []


def advantage(model, trace, memory):
    attempts = [trace] + trace.group
    good, bad = [t for t in attempts if t.correct], [t for t in attempts if not t.correct]
    if not good or not bad:
        return None                                   # без контраста преимущества нет
    shown = "\n\n".join(f"## Attempt ({'correct' if t.correct else 'wrong'})\n{t.output}" for t in attempts)
    return model.one("You are a reflector.", ADVANTAGE.format(
        question=trace.question, target=trace.target, attempts=shown)).output


def stash(model, memory, summary):
    memory.add(summary, kind="episode")               # эпизоды решателю не показываются


def consolidate(model, memory, traces):
    summaries = [r for r in memory.records if r.kind == "episode"]
    if not summaries:
        return
    shown = "\n".join(f"[{r.id}] {r.text}" for r in memory.records if r.kind == "insight") or "(empty)"
    r = model.run("You are a curator.", CONSOLIDATE.format(
        memory=shown, summaries="\n".join(f"- {s.text}" for s in summaries)), output=Ops).output
    for op in (r.ops if r else []):
        text = " ".join(op.text.split()[:WORDS])
        if op.op == "add" and text:
            memory.add(text)
        elif op.op == "modify" and memory.get(op.id) and text:
            memory.get(op.id).text = text
        elif op.op == "delete" and memory.get(op.id):
            memory.drop(op.id)
    for s in summaries:
        memory.drop(s.id)


def inject(memory):
    return "\n".join(f"- {r.text}" for r in memory.records if r.kind == "insight")


tfgrpo = Method("tfgrpo", inject=inject, reflect=advantage, curate=stash, group=4, every=BATCH, batch=consolidate)
