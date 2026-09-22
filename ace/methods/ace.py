"""ACE (Agentic Context Engineering).

    1 память      пункты со счётчиками helpful / harmful
    2 инжект      вся память
    3 сигнал      верный ответ
    4 обновление  reflector: уроки и метки пунктов -> curator правит память -> удаление вредных пунктов
"""
from typing import Literal

from pydantic import BaseModel

from .. import fs, inject, update
from ..feedback import Feedback
from ..loop import Method
from ..memory import ALL
from ..update import Delta, Update

# 1. память

MEMORY = {"bullet": ALL}

# 4. обновление

REFLECT = """Compare the attempted solution with the correct answer and extract at most 3 short lessons
that would help solve similar tasks. Also name the memory bullets that helped and the ones that misled.
{form}

## Task
{question}

## Attempted solution
{output}

## Verdict
{verdict}

## Memory bullets available during the attempt
{memory}"""

CURATE = """Merge the lessons into memory using the tools: create a bullet in memory/ only if it is genuinely new and transferable,
edit a bullet (read it first) if a lesson refines it. Do nothing for duplicates. When done, reply "done".

## Lessons
{lessons}

## Memory
{memory}"""


class Reflection(BaseModel):
    lessons: list[str]
    helpful: list[str] = []
    harmful: list[str] = []


class Op(BaseModel):
    op: Literal["ADD", "UPDATE"]
    text: str
    id: str = ""


class Ops(BaseModel):
    ops: list[Op]


def reflect(format="json", bullets="all"):
    """format: json — маленькая схема; text — свободное письмо, куратор разбирает его сам.
    bullets: all — reflector видит всю память; used — только пункты, которые решатель назвал (как в апстриме)."""
    def reflect(ctx, ep, memory):
        shown = memory.text() if bullets == "all" else "\n".join(f"[{i}] {memory.get(i).text}" for i in ep.used if memory.get(i))
        prompt = REFLECT.format(question=ep.question, output=ep.output, verdict=ep.verdict(),
                                memory=shown or "(empty)", form="Write freely." if format == "text" else "")
        if format == "text":
            text = ctx.model.one("You are a reflector.", prompt).output
            return Delta(lessons=[text]) if text else None
        r = ctx.model.run("You are a reflector.", prompt, output=Reflection).output
        return Delta(lessons=r.lessons, helpful=r.helpful, harmful=r.harmful) if r else None
    return reflect


def curate(mode="tools"):
    """mode: tools — файловые инструменты по одной операции; json — все операции одной схемой; rewrite — вся память заново."""
    def curate(ctx, memory, deltas):
        for d in deltas:
            update.count(memory, d.helpful, d.harmful)
            if d.lessons:
                merge(ctx.model, memory, d.shown(), mode)
    return curate


def merge(model, memory, lessons, mode):
    if mode == "tools":
        files = "\n".join(f"memory/{r.id}: {r.text}" for r in memory.records) or "(empty)"
        model.run("You are a curator.", CURATE.format(lessons=lessons, memory=files),
                  tools=fs.TOOLS, deps=fs.FS({"memory": fs.Mount(memory)}), rounds=6)
        return
    prompt = CURATE.format(lessons=lessons, memory=memory.text() or "(empty)")
    if mode == "json":
        r = model.run("You are a curator.", prompt.replace("using the tools", "as a list of ADD/UPDATE operations"), output=Ops).output
        for op in (r.ops if r else []):
            if op.op == "ADD":
                memory.add(op.text)
            elif memory.get(op.id):
                memory.edit(op.id, op.text)
    else:
        new = model.one("You are a curator.", prompt.replace("using the tools", "by rewriting the whole memory")
                        .replace('reply "done"', "return only the new memory, one bullet per line")).output
        if new:
            memory.rewrite(next(iter(memory.schema)), new.strip())


def propose_add(ctx, memory, deltas):
    """Куратор апстрима: только ADD, применяет код; счётчики по меткам reflector."""
    for d in deltas:
        update.count(memory, d.helpful, d.harmful)
        if not d.lessons:
            continue
        r = ctx.model.run("You are a curator.", CURATE.format(lessons=d.shown(), memory=memory.text() or "(empty)")
                          .replace("using the tools", "as a list of ADD operations"), output=Ops).output
        for op in (r.ops if r else []):
            if op.op == "ADD" and op.text.strip():
                memory.add(op.text.strip())


def prune(ctx, memory, before):
    for r in list(memory.records):
        if r.harmful >= 3 and r.harmful > r.helpful:
            memory.drop(r.id)


ace = Method("ace", MEMORY, inject.full(), Feedback("golden"),
             Update(reflect(), curate(), prune))

# ACE как в апстриме: самоотчёт bullet_ids, reflector метит только названные пункты,
# куратор только добавляет, grow-and-refine по эмбеддингам
ace_exact = Method("ace_exact", MEMORY, inject.full(), Feedback("golden", usage="self"),
                   Update(reflect(bullets="used"), propose_add, update.chain(update.dedup(), prune), needs_usage=True))
