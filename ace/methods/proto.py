"""Прототип.

    1 память      типизированные записи с политикой по типу:
                  constraint  только add и narrow
                  procedure   любые операции
                  insight     любые операции, первый кандидат на удаление
                  episode     только add; решателю не показывается, это provenance
    2 инжект      constraint целиком в промпте, procedure и insight каталогом, тело по read(path)
    3 сигнал      верный ответ; что решатель прочёл, записывает среда (read)
    4 обновление  рефлексия только по прочитанным записям -> куратор операциями add / patch / narrow / merge
                  -> бюджет доли промпта
"""
from typing import Literal

from pydantic import BaseModel
from pydantic_ai import RunContext

from .. import bound, curate as stages, inject, prompts
from ..feedback import Feedback
from ..loop import Method
from ..memory import ALL, Forbidden, Memory
from ..update import Delta, Update, ask

# 1. память

MEMORY = {"constraint": ("add", "narrow"), "procedure": ALL, "insight": ALL, "episode": ("add",)}
Kind = Literal["constraint", "procedure", "insight"]

# 2. инжект

INJECT = inject.catalog(always=("constraint",), listed=("procedure", "insight"))

# 4. обновление

REFLECT = prompts.load("proto_reflect.txt")
CURATE = prompts.load("proto_curate.txt")
CURATE_JSON = prompts.Prompt(CURATE.text.replace("tool calls", "operations (ids go in `ids`)"))
CURATE_REWRITE = prompts.Prompt(CURATE.text.replace(
    "with as few tool calls as possible: add, patch, merge, narrow",
    "by returning the full new list of entries; keep the id of an entry you keep, leave it empty for a new one"))


class Lesson(BaseModel):
    kind: Kind
    when: str          # одна строка: когда применять
    text: str

    def __str__(self):
        return f"{self.kind}, when {self.when}: {self.text}"


class Reflection(BaseModel):
    helpful: list[str] = []
    harmful: list[str] = []
    lessons: list[Lesson] = []


def reflect_fields(form):
    def fields(ctx, ep, memory, **extra):
        used = "\n".join(f"[{i}] {memory.get(i).text}" for i in ep.used if memory.get(i)) or "(none)"
        return dict(question=ep.question, output=ep.output, verdict=ep.verdict(), used=used, form=form)
    return fields


def episode(ep):
    return dict(text=f"{ep.verdict()}: {ep.answer}", when=ep.question[:80])


def reflect(format="json"):
    if format == "text":
        return ask(REFLECT, reflect_fields("Write freely."), system="You are a reflector.",
                   then=lambda text, ctx, ep, memory, **_: Delta(lessons=[text] if text else [], episode=episode(ep)))
    return ask(REFLECT, reflect_fields(""), Reflection, system="You are a reflector.",
               then=lambda r, ctx, ep, memory, **_: Delta(lessons=(r or Reflection()).lessons, helpful=(r or Reflection()).helpful,
                                                        harmful=(r or Reflection()).harmful, episode=episode(ep)))


# операции куратора; память сама не даст нарушить политику типа

def add(ctx: RunContext[Memory], kind: Kind, when: str, text: str) -> str:
    """Add a new entry."""
    return ctx.deps.add(text, kind=kind, when=when).id


def patch(ctx: RunContext[Memory], id: str, text: str) -> str:
    """Rewrite the text of a procedure or insight."""
    if not ctx.deps.get(id):
        return "no such id"
    try:
        ctx.deps.edit(id, text)
    except Forbidden:
        return "not allowed"
    return "ok"


def narrow(ctx: RunContext[Memory], id: str, when: str) -> str:
    """Make the applicability condition of an entry more specific."""
    if not ctx.deps.get(id):
        return "no such id"
    ctx.deps.edit(id, when=when)
    return "ok"


def merge(ctx: RunContext[Memory], ids: list[str], when: str, text: str) -> str:
    """Replace several procedures or insights with one entry."""
    recs = [ctx.deps.get(i) for i in ids if ctx.deps.get(i)]
    if len(recs) < 2 or any("delete" not in ctx.deps.ops(r.kind) for r in recs):
        return "not allowed"
    keep, *rest = recs
    ctx.deps.edit(keep.id, text, when)
    keep.helpful, keep.harmful = sum(r.helpful for r in recs), sum(r.harmful for r in recs)
    for r in rest:
        ctx.deps.drop(r.id)
    return keep.id


class Op(BaseModel):
    op: Literal["add", "patch", "narrow", "merge"]
    kind: Kind = "insight"
    ids: list[str] = []
    when: str = ""
    text: str = ""


class Ops(BaseModel):
    ops: list[Op] = []


class Entry(Lesson):
    id: str = ""


class Entries(BaseModel):
    entries: list[Entry] = []


class Deps:
    """Подстановка RunContext, когда операции применяет код, а не модель через tool."""
    def __init__(self, memory):
        self.deps = memory


def apply(memory, op):
    ctx = Deps(memory)
    if op.op == "add":
        return add(ctx, op.kind, op.when, op.text)
    if op.op == "merge":
        return merge(ctx, op.ids, op.when, op.text)
    id = op.ids[0] if op.ids else ""
    return patch(ctx, id, op.text) if op.op == "patch" else narrow(ctx, id, op.when)


def entries(memory):
    shown = "\n".join(f"[{r.id}] ({r.kind}; when: {r.when}) {r.text}" for r in memory.of("constraint", "procedure", "insight"))
    return shown or "(empty)"


def fields(ctx, memory, d, **extra):
    return dict(lessons=d.shown(), memory=entries(memory))


def apply_all(r, ctx, memory, d, **extra):
    for op in (r.ops if r else []):
        apply(memory, op)


def replace_all(r, ctx, memory, d, **extra):
    """Полный новый список: оставленные по id правятся, остальные уходят; constraint не трогаются."""
    if not r:
        return
    keep = {e.id: e for e in r.entries if e.id}
    for rec in memory.of("constraint", "procedure", "insight"):
        if rec.id in keep:
            memory.edit(rec.id, keep[rec.id].text if rec.kind != "constraint" else None, keep[rec.id].when)
        elif rec.kind != "constraint":
            memory.drop(rec.id)
    for e in r.entries:
        if not e.id:
            memory.add(e.text, kind=e.kind, when=e.when)


def add_episode(ctx, memory, d):
    if d.episode:
        memory.add(kind="episode", **d.episode)


def curate(mode="tools"):
    """mode: tools — по одной операции за вызов; json — все операции одной схемой; rewrite — все записи заново.
    Эпизоды ни один режим не трогает."""
    merge_lessons = {
        "tools": stages.tools(CURATE, fields, lambda memory, d: memory, rounds=4, toolset=(add, patch, narrow, merge)),
        "json": ask(CURATE_JSON, fields, Ops, system="You are a curator.", then=apply_all),
        "rewrite": ask(CURATE_REWRITE, fields, Entries, system="You are a curator.", then=replace_all),
    }[mode]
    return stages.each(add_episode, stages.count, stages.admit(lambda ctx, memory, d: bool(d.lessons), merge_lessons))


proto = Method("proto", MEMORY, INJECT, Feedback("golden", usage="env"),
               Update(reflect(), curate(), bound.budget(0.25), needs_usage=True))
