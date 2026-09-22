"""MCE: два уровня. Базовый куратор раз в батч переписывает контекст по инструкции (skill).
Мета-уровень раз в несколько батчей предлагает новую инструкцию, (1+1)-ES: кандидат
принимается, если контекст по нему даёт на val не меньше верных, чем по текущей."""
from ..loop import Method, solve
from ..memory import Memory

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
Batch accuracies so far: {history}. Previous instructions tried and their validation scores:
{tried}

## Current instruction
{skill}

## Current knowledge file it produced
{memory}

Propose a changed instruction (one or two concrete changes) so the next batches score higher.
Return only the new instruction."""

BATCH, META_EVERY = 5, 3
skill, history, tried = SEED_SKILL, [], []


def rewrite(model, memory, traces, instruction):
    shown = "\n\n".join(f"### {'correct' if t.correct else f'wrong, expected {t.target}'}\n{t.output}" for t in traces)
    new = model.one("You are a context curator.", CURATE.format(
        skill=instruction, memory=memory.text() or "(empty)", correct=sum(t.correct for t in traces), n=len(traces), batch=shown)).text
    memory.replace_all(new.strip())


def val_score(model, task, memory):
    return sum(solve(model, task, memory, mce, item).correct for item in task.load("val"))


def batch(model, memory, traces, task):
    global skill
    history.append(sum(t.correct for t in traces))
    before = list(memory.records)
    rewrite(model, memory, traces, skill)
    if len(history) % META_EVERY:
        return
    candidate = model.one("You are a meta-curator.", META.format(
        history=history, tried="\n".join(f"- {s:.60}... -> {v}" for s, v in tried) or "(none)",
        skill=skill, memory=memory.text())).text.strip()
    trial = Memory(records=before, counter=memory.counter)
    rewrite(model, trial, traces, candidate)
    cur, new = val_score(model, task, memory), val_score(model, task, trial)
    tried.append((candidate, new))
    if new >= cur:
        skill, memory.records = candidate, trial.records


mce = Method("mce", every=BATCH, batch=batch, signal="golden")
