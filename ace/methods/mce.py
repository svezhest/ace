"""MCE: два уровня. Базовый куратор раз в батч переписывает знания по инструкции (skill).
Мета-уровень раз в несколько батчей переписывает саму инструкцию, глядя на ход точности."""
from ..loop import Method

SEED_SKILL = """Keep a compact knowledge file for this task family. After each batch of attempts:
keep rules that led to correct answers, fix or remove rules that led to mistakes,
add new transferable rules from the mistakes. Prefer concrete procedures over generalities."""

CURATE = """{skill}

## Current knowledge
{memory}

## Last batch ({correct}/{n} correct)
{batch}

Return only the new knowledge file."""

META = """You improve the instruction a curator follows when maintaining a knowledge file.
Batch accuracies so far: {history}.

## Current instruction
{skill}

## Current knowledge file it produced
{memory}

Rewrite the instruction so the next batches score higher. Return only the new instruction."""

BATCH, META_EVERY = 5, 3
skill, history = SEED_SKILL, []


def batch(model, memory, traces):
    global skill
    history.append(sum(t.correct for t in traces))
    shown = "\n\n".join(f"### {'correct' if t.correct else f'wrong, expected {t.target}'}\n{t.output}" for t in traces)
    memory.replace_all(model.one("You are a context curator.", CURATE.format(
        skill=skill, memory=memory.text() or "(empty)", correct=history[-1], n=len(traces), batch=shown)).text.strip())
    if len(history) % META_EVERY == 0:
        skill = model.one("You are a meta-curator.", META.format(
            history=history, skill=skill, memory=memory.text())).text.strip()


mce = Method("mce", every=BATCH, batch=batch, signal="golden")
