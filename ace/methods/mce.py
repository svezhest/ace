"""MCE (Meta Context Engineering).

    1 память      один файл знаний
    2 инжект      весь файл
    3 сигнал      верный ответ
    4 обновление  раз в батч куратор переписывает файл по своей инструкции (skill);
                  мета-уровень раз в несколько батчей предлагает новую инструкцию, (1+1)-ES:
                  кандидат принимается, если файл по нему даёт на val не меньше верных.
                  Инструкция и история это состояние обновления, а не память.
"""
from .. import inject
from ..feedback import Feedback
from ..loop import Method
from ..update import Update, snapshot

# 1. память

MEMORY = {"knowledge": ("add", "edit")}

# 4. обновление

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


def keep(ctx, ep, memory):
    return ep


def rewrite(model, memory, episodes, skill):
    shown = "\n\n".join(f"### {ep.verdict()}\n{ep.output}" for ep in episodes)
    new = model.one("You are a context curator.", CURATE.format(
        skill=skill, memory=inject.plain(memory.records) or "(empty)", correct=sum(bool(ep.ok) for ep in episodes),
        n=len(episodes), batch=shown)).text
    memory.rewrite("knowledge", new.strip())


def curate(ctx, memory, episodes):
    st = ctx.state
    skill, history, tried = st.setdefault("skill", SEED_SKILL), st.setdefault("history", []), st.setdefault("tried", [])
    history.append(sum(bool(ep.ok) for ep in episodes))
    before = snapshot(memory)
    rewrite(ctx.model, memory, episodes, skill)
    if len(history) % META_EVERY:
        return
    candidate = ctx.model.one("You are a meta-curator.", META.format(
        history=history, tried="\n".join(f"- {s:.60}... -> {v}" for s, v in tried) or "(none)",
        skill=skill, memory=inject.plain(memory.records))).text.strip()
    rewrite(ctx.model, before, episodes, candidate)
    cur, new = sum(c for c, _ in ctx.evaluate(memory)), sum(c for c, _ in ctx.evaluate(before))
    tried.append((candidate, new))
    if new >= cur:
        st["skill"], memory.records, memory.counter = candidate, before.records, before.counter


mce = Method("mce", MEMORY, inject.full(inject.plain), Feedback("golden"), Update(keep, curate, every=BATCH))
