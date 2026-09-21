"""ACE: reflector видит верный ответ и выдаёт уроки, curator правит память по одной записи через tools."""
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


def curate(model, memory, lessons):
    shown = lessons if isinstance(lessons, str) else "\n".join(f"- {l}" for l in lessons)
    model.run("You are a curator.", CURATE.format(lessons=shown, memory=memory.text() or "(empty)"),
              tools=(add, update), deps=memory, rounds=4)


def bound(model, memory, *_):
    for r in list(memory.records):
        if r.harmful >= 3 and r.harmful > r.helpful:
            memory.drop(r.id)


ace = Method("ace", reflect=reflect(), curate=curate, bound=bound)
