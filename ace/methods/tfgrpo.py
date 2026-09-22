"""Training-Free GRPO.

    1 память      библиотека опытов, каждый до 32 слов
    2 инжект      вся библиотека
    3 сигнал      верный ответ для каждой из G попыток
    4 обновление  по группе попыток модель пишет, чем верные отличались от неверных (семантическое
                  преимущество); раз в батч сводки сводятся в библиотеку операциями add / modify / delete / keep
    решатель      G = 1 + 4 попытки на вопрос
"""
from typing import Literal

from pydantic import BaseModel

from .. import inject
from ..feedback import Feedback
from ..loop import Method, Solver
from ..memory import ALL
from ..update import Update

# 1. память

MEMORY = {"experience": ALL}

# 4. обновление

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


def advantage(ctx, ep, memory):
    attempts = [ep] + ep.group
    if all(a.ok for a in attempts) or not any(a.ok for a in attempts):
        return None                                   # без контраста преимущества нет
    shown = "\n\n".join(f"## Attempt ({'correct' if a.ok else 'wrong'})\n{a.output}" for a in attempts)
    return ctx.model.one("You are a reflector.", ADVANTAGE.format(question=ep.question, target=ep.target, attempts=shown)).output


def consolidate(ctx, memory, summaries):
    r = ctx.model.run("You are a curator.", CONSOLIDATE.format(
        memory=memory.text() or "(empty)", summaries="\n".join(f"- {s}" for s in summaries)), output=Ops).output
    for op in (r.ops if r else []):
        text = " ".join(op.text.split()[:WORDS])
        if op.op == "add" and text:
            memory.add(text)
        elif op.op == "modify" and memory.get(op.id) and text:
            memory.edit(op.id, text)
        elif op.op == "delete" and memory.get(op.id):
            memory.drop(op.id)


tfgrpo = Method("tfgrpo", MEMORY, inject.full(inject.dashed), Feedback("golden"),
                Update(advantage, consolidate, every=BATCH), Solver(samples=4))
