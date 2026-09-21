"""Dynamic Cheatsheet: один вызов после каждой задачи переписывает всю память целиком, без метки."""
from ..loop import Method

CURATOR = """You maintain a cheatsheet of reusable strategies, formulas and warnings for solving tasks like the one below.
Rewrite the whole cheatsheet: keep what is useful, fix or remove what is wrong, add new transferable insights. Keep it compact.

## Current cheatsheet
{cheatsheet}

## Task
{question}

## Attempted solution
{output}

Return only the new cheatsheet."""


def reflect(model, trace, memory):
    return model.one("You are a careful curator of a cheatsheet.",
                     CURATOR.format(cheatsheet=memory.text() or "(empty)", question=trace.question, output=trace.output)).text


def curate(model, memory, new_text):
    memory.replace_all(new_text.strip())


dc = Method("dc", reflect=reflect, curate=curate, signal="none")
