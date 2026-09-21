"""ACE: reflector видит верный ответ, curator выдаёт дельты ADD/UPDATE, память растёт bullet'ами."""
import json
import re

from ..loop import Method

REFLECT = """Compare the attempted solution with the correct answer and extract lessons that would help solve similar tasks.
Return JSON: {{"lessons": [{{"text": "...", "reason": "..."}}], "helpful": ["ids of memory bullets that helped"], "harmful": ["ids that misled"]}}

## Task
{question}

## Attempted solution
{output}

## Verdict
{verdict}

## Memory bullets available during the attempt
{memory}"""

CURATE = """Given the lessons and the existing memory, output JSON operations:
{{"ops": [{{"op": "ADD", "text": "..."}}, {{"op": "UPDATE", "id": "r3", "text": "..."}}]}}
Add only genuinely new and transferable bullets; update a bullet if a lesson refines it. Return only JSON.

## Lessons
{lessons}

## Memory
{memory}"""


def parse_json(text):
    """Модель иногда ломает JSON; тогда считаем, что она ничего не сказала."""
    m = re.search(r"\{.*\}", text, re.S)
    try:
        return json.loads(m.group(0)) if m else {}
    except json.JSONDecodeError:
        return {}


def reflect(model, trace, memory):
    verdict = "correct" if trace.correct else f"wrong, correct answer: {trace.target}"
    r = parse_json(model.one("You are a reflector.", REFLECT.format(
        question=trace.question, output=trace.output, verdict=verdict, memory=memory.text() or "(empty)")).text)
    for id in r.get("helpful", []):
        if memory.get(id): memory.get(id).helpful += 1
    for id in r.get("harmful", []):
        if memory.get(id): memory.get(id).harmful += 1
    return r.get("lessons") or None


def curate(model, memory, lessons):
    ops = parse_json(model.one("You are a curator.", CURATE.format(
        lessons=json.dumps(lessons, ensure_ascii=False), memory=memory.text() or "(empty)")).text).get("ops", [])
    for op in ops:
        if op.get("op") == "ADD" and op.get("text"):
            memory.add(op["text"])
        elif op.get("op") == "UPDATE" and memory.get(op.get("id", "")):
            memory.get(op["id"]).text = op["text"]


def bound(model, memory, *_):
    for r in list(memory.records):
        if r.harmful >= 3 and r.harmful > r.helpful:
            memory.drop(r.id)


ace = Method("ace", reflect=reflect, curate=curate, bound=bound)
