"""Training-Free GRPO: G сэмплов на вопрос, рефлексия контрастная, верные против неверных."""
from pydantic import BaseModel

from ..loop import Method

CONTRAST = """Below are several attempts at the same task; some are correct, some are not.
Explain what the correct ones did that the wrong ones did not, as short reusable experiences.

## Task
{question}

## Correct answer
{target}

{attempts}"""


class Experiences(BaseModel):
    experiences: list[str]


def reflect(model, trace, memory):
    attempts = [trace] + trace.group
    good, bad = [t for t in attempts if t.correct], [t for t in attempts if not t.correct]
    if not good or not bad:
        return None                                   # без контраста учиться не на чем
    shown = "\n\n".join(f"## Attempt ({'correct' if t.correct else 'wrong'})\n{t.output}" for t in attempts)
    r = model.run("You are a reflector.", CONTRAST.format(
        question=trace.question, target=trace.target, attempts=shown), output=Experiences).output
    return r.experiences if r and r.experiences else None


def curate(model, memory, experiences):
    for e in experiences:
        memory.add(e)


tfgrpo = Method("tfgrpo", reflect=reflect, curate=curate, group=4)
