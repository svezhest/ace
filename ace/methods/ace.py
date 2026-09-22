"""ACE: reflector видит верный ответ и выдаёт уроки, curator правит память по одной записи через tools."""
from typing import Literal

from pydantic import BaseModel
from pydantic_ai import RunContext

from ..loop import Method
from ..memory import Memory

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

CURATE = """Merge the lessons into memory using the tools: add a bullet only if it is genuinely new and transferable,
update a bullet if a lesson refines it. Do nothing for duplicates. When done, reply "done".

## Lessons
{lessons}

## Memory
{memory}"""


class Op(BaseModel):
    op: Literal["ADD", "UPDATE"]
    text: str
    id: str = ""


class Ops(BaseModel):
    ops: list[Op]


class Reflection(BaseModel):
    lessons: list[str]
    helpful: list[str] = []
    harmful: list[str] = []


def add(ctx: RunContext[Memory], text: str) -> str:
    """Add a new memory bullet."""
    return ctx.deps.add(text).id


def update(ctx: RunContext[Memory], id: str, text: str) -> str:
    """Replace the text of an existing bullet."""
    rec = ctx.deps.get(id)
    if rec:
        rec.text = text
    return "ok" if rec else "no such id"


def reflect(format="json"):
    """format: json — маленькая схема; text — свободное письмо, куратор разбирает его сам."""
    def reflect(model, trace, memory):
        verdict = "correct" if trace.correct else f"wrong, correct answer: {trace.target}"
        prompt = REFLECT.format(question=trace.question, output=trace.output, verdict=verdict,
                                memory=memory.text() or "(empty)", form="Write freely." if format == "text" else "")
        if format == "text":
            return model.one("You are a reflector.", prompt).output
        r = model.run("You are a reflector.", prompt, output=Reflection).output
        if not r:
            return None
        for id in r.helpful:
            if memory.get(id): memory.get(id).helpful += 1
        for id in r.harmful:
            if memory.get(id): memory.get(id).harmful += 1
        return r.lessons or None
    return reflect


def curate(mode="tools"):
    """mode: tools — по одной операции за вызов; json — все операции одной схемой; rewrite — вся память заново."""
    def curate(model, memory, lessons):
        shown = lessons if isinstance(lessons, str) else "\n".join(f"- {l}" for l in lessons)
        prompt = CURATE.format(lessons=shown, memory=memory.text() or "(empty)")
        if mode == "tools":
            model.run("You are a curator.", prompt, tools=(add, update), deps=memory, rounds=4)
        elif mode == "json":
            r = model.run("You are a curator.", prompt.replace("using the tools", "as a list of ADD/UPDATE operations"),
                          output=Ops).output
            for op in (r.ops if r else []):
                add(Deps(memory), op.text) if op.op == "ADD" else update(Deps(memory), op.id, op.text)
        else:
            new = model.one("You are a curator.", prompt.replace("using the tools", "by rewriting the whole memory")
                            .replace('reply "done"', "return only the new memory, one bullet per line")).output
            memory.replace_all(new.strip()) if new else None
    return curate


class Deps:
    """Подстановка RunContext, когда операции применяем сами, а не через tool."""
    def __init__(self, memory):
        self.deps = memory


def bound(model, memory, *_):
    for r in list(memory.records):
        if r.harmful >= 3 and r.harmful > r.helpful:
            memory.drop(r.id)


ace = Method("ace", reflect=reflect(), curate=curate(), bound=bound)
