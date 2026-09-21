"""Прототип: типизированные записи, каталог вместо полной памяти, рефлексия только по вызванным
записям, куратор правит память через tools с политикой по типу записи.

    constraint  всегда в промпте; только add и narrow
    procedure   в каталоге, тело по вызову; patch и merge
    insight     в каталоге; любые операции, первый кандидат на удаление
    episode     решателю не показывается; append-only, сырьё для рефлексии
"""
from typing import Literal

from pydantic import BaseModel
from pydantic_ai import RunContext

from .. import bound
from ..env import Skills
from ..loop import Method
from ..memory import Memory

Kind = Literal["constraint", "procedure", "insight"]

REFLECT = """Judge the attempt and the memory entries the solver actually read: which helped, which misled.
Then give at most 2 lessons that transfer to other tasks (none is fine). {form}
constraint = a hard rule that must always hold; procedure = how to do a kind of step; insight = a hint.

## Task
{question}

## Attempt
{output}

## Verdict
{verdict}

## Entries the solver read
{used}"""

CURATE = """Merge the lessons into memory with as few tool calls as possible: add, patch, merge, narrow.
Constraints are only added or narrowed, never rewritten. Skip a lesson that duplicates an entry. Reply "done" when finished.

## Lessons
{lessons}

## Memory
{memory}"""


class Lesson(BaseModel):
    kind: Kind
    when: str          # одна строка: когда применять
    text: str


class Reflection(BaseModel):
    helpful: list[str] = []
    harmful: list[str] = []
    lessons: list[Lesson] = []


def add(ctx: RunContext[Memory], kind: Kind, when: str, text: str) -> str:
    """Add a new entry."""
    return ctx.deps.add(text, kind=kind, when=when).id


def patch(ctx: RunContext[Memory], id: str, text: str) -> str:
    """Rewrite the text of a procedure or insight."""
    rec = ctx.deps.get(id)
    if not rec or rec.kind == "constraint":
        return "not allowed"
    rec.text = text
    return "ok"


def narrow(ctx: RunContext[Memory], id: str, when: str) -> str:
    """Make the applicability condition of an entry more specific."""
    rec = ctx.deps.get(id)
    if not rec:
        return "no such id"
    rec.when = when
    return "ok"


def merge(ctx: RunContext[Memory], ids: list[str], when: str, text: str) -> str:
    """Replace several procedures or insights with one entry."""
    recs = [ctx.deps.get(i) for i in ids if ctx.deps.get(i)]
    if len(recs) < 2 or any(r.kind == "constraint" for r in recs):
        return "not allowed"
    keep, *rest = recs
    keep.text, keep.when = text, when
    keep.helpful, keep.harmful = sum(r.helpful for r in recs), sum(r.harmful for r in recs)
    for r in rest:
        ctx.deps.drop(r.id)
    return keep.id


def by_kind(memory, *kinds):
    return [r for r in memory.records if r.kind in kinds]


def inject(memory):
    rules = "\n".join(f"- {r.text}" for r in by_kind(memory, "constraint")) or "(none)"
    catalog = "\n".join(f"[{r.id}] {r.when}" for r in by_kind(memory, "procedure", "insight")) or "(none)"
    return f"Rules:\n{rules}\n\nEntries you can read with use_skill:\n{catalog}"


def reflect(format="json"):
    def reflect(model, trace, memory):
        verdict = "correct" if trace.correct else f"wrong, correct answer: {trace.target}"
        used = "\n".join(f"[{i}] {memory.get(i).text}" for i in trace.used if memory.get(i)) or "(none)"
        memory.add(f"{verdict}: {trace.answer}", kind="episode", when=trace.question[:80])
        prompt = REFLECT.format(question=trace.question, output=trace.output, verdict=verdict, used=used,
                                form="Write freely." if format == "text" else "")
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
    shown = "\n".join(f"[{r.id}] ({r.kind}; when: {r.when}) {r.text}" for r in by_kind(memory, "constraint", "procedure", "insight"))
    lessons = lessons if isinstance(lessons, str) else "\n".join(f"- {l.kind}, when {l.when}: {l.text}" for l in lessons)
    model.run("You are a curator.", CURATE.format(lessons=lessons, memory=shown or "(empty)"),
              tools=(add, patch, narrow, merge), deps=memory, rounds=4)


proto = Method("proto", inject=inject, reflect=reflect(), curate=curate, env=Skills(),
               bound=bound.chain(bound.budget(0.25), bound.gate()))
