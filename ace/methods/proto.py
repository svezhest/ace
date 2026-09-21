"""Прототип: типизированные записи, каталог вместо полной памяти, рефлексия только по вызванным
записям, пять операций куратора с политикой по типу записи.

    constraint  всегда в промпте; только ADD и NARROW
    procedure   в каталоге, тело по вызову; PATCH и MERGE
    insight     в каталоге; любые операции, первый кандидат на удаление
    episode     решателю не показывается; append-only, сырьё для рефлексии
"""
import json

from .. import bound
from ..env import Skills
from ..loop import Method
from .ace import parse_json

REFLECT = """Judge the attempt and the memory entries the solver actually read. Return JSON:
{{"helpful": ["ids that helped"], "harmful": ["ids that misled"],
  "lessons": [{{"kind": "constraint|procedure|insight", "when": "one line: when to apply", "text": "..."}}]}}
constraint = a hard rule that must always hold; procedure = how to do a kind of step; insight = a hint.
Only lessons that transfer to other tasks. Empty lessons list is fine.

## Task
{question}

## Attempt
{output}

## Verdict
{verdict}

## Entries the solver read
{used}"""

CURATE = """Merge the lessons into memory with as few operations as possible. Return JSON:
{{"ops": [{{"op": "ADD", "kind": "...", "when": "...", "text": "..."}},
          {{"op": "PATCH", "id": "r3", "text": "..."}},
          {{"op": "MERGE", "ids": ["r3", "r5"], "when": "...", "text": "..."}},
          {{"op": "NARROW", "id": "r3", "when": "..."}},
          {{"op": "NOOP"}}]}}
Rules: constraints are only added or narrowed, never rewritten. Prefer NOOP to a near-duplicate.

## Lessons
{lessons}

## Memory
{memory}"""

ALLOWED = {"constraint": {"ADD", "NARROW"}, "procedure": {"ADD", "PATCH", "MERGE", "NARROW"},
           "insight": {"ADD", "PATCH", "MERGE", "NARROW"}, "episode": set()}


def by_kind(memory, *kinds):
    return [r for r in memory.records if r.kind in kinds]


def inject(memory):
    rules = "\n".join(f"- {r.text}" for r in by_kind(memory, "constraint")) or "(none)"
    catalog = "\n".join(f"[{r.id}] {r.when}" for r in by_kind(memory, "procedure", "insight")) or "(none)"
    return f"Rules:\n{rules}\n\nEntries you can read with USE SKILL:\n{catalog}"


def reflect(model, trace, memory):
    verdict = "correct" if trace.correct else f"wrong, correct answer: {trace.target}"
    used = "\n".join(f"[{i}] {memory.get(i).text}" for i in trace.used if memory.get(i)) or "(none)"
    r = parse_json(model.one("You are a reflector.", REFLECT.format(
        question=trace.question, output=trace.output, verdict=verdict, used=used)).text)
    for id in r.get("helpful", []):
        if memory.get(id): memory.get(id).helpful += 1
    for id in r.get("harmful", []):
        if memory.get(id): memory.get(id).harmful += 1
    memory.add(f"{verdict}: {trace.answer}", kind="episode", when=trace.question[:80])
    return r.get("lessons") or None


def curate(model, memory, lessons):
    shown = "\n".join(f"[{r.id}] ({r.kind}; when: {r.when}) {r.text}" for r in by_kind(memory, "constraint", "procedure", "insight"))
    ops = parse_json(model.one("You are a curator.", CURATE.format(
        lessons=json.dumps(lessons, ensure_ascii=False), memory=shown or "(empty)")).text).get("ops", [])
    for op in ops:
        apply(memory, op)


def apply(memory, op):
    name = op.get("op")
    if name == "ADD" and op.get("text") and op.get("kind") in ALLOWED:
        memory.add(op["text"], kind=op["kind"], when=op.get("when", ""))
        return
    ids = op.get("ids") or [op.get("id")]
    recs = [memory.get(i) for i in ids if memory.get(i)]
    if not recs or any(name not in ALLOWED[r.kind] for r in recs):
        return
    if name == "PATCH":
        recs[0].text = op.get("text") or recs[0].text
    elif name == "NARROW":
        recs[0].when = op.get("when") or recs[0].when
    elif name == "MERGE" and op.get("text"):
        keep, *rest = recs
        keep.text, keep.when = op["text"], op.get("when") or keep.when
        keep.helpful, keep.harmful = sum(r.helpful for r in recs), sum(r.harmful for r in recs)
        for r in rest:
            memory.drop(r.id)


proto = Method("proto", inject=inject, reflect=reflect, curate=curate, env=Skills(),
               bound=bound.chain(bound.budget(0.25), bound.gate()))
