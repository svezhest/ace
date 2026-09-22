"""Стадия reflect обновления: эпизод -> дельта; память не меняет. Блок: block(ctx, ep, memory, **extra) -> результат.
Результат None обрывает цепочку.

    ask(...)                        один вызов модели по промпту метода (update.ask)
    keep                            эпизод как есть: всё решает куратор (DC-RS, MCE)
    seq(*blocks)                    по очереди, результат предыдущего в extra["prev"]
    when(test, block)               только если test(ctx, ep) (TF-GRPO: группа верна частично)
    rounds(block, n)                при неверном ответе: рефлексия -> счётчики на копии памяти -> новая
                                    попытка с рефлексией, до n раз или до верного ответа (ACE)
    per_step(block, steps)          по шагам траектории; найденное раньше в extra["found"] (SCOPE)
    perspectives(block)             по попытке каждой перспективы (SCOPE K=2)
    best_of(block, n, select)       n кандидатов при T=0.7 и выбор (SCOPE Best-of-N)
    each_attempt(block)             по каждой попытке группы, список пар (попытка, результат) (TF-GRPO)
    log_gain, future_gain           прирост лучшей попытки над средней и записей её выборки (EvoLib IG и Future IG)"""
import math
from dataclasses import replace

from .update import Delta, count, seq, snapshot, when  # noqa: F401  seq и when общие со стадией curate


def keep(ctx, ep, memory, **extra):
    return ep


def rounds(inner, n=3, note=lambda d: d.lessons[-1]):
    """inner -> Delta. Счётчики каждого раунда сразу идут в копию памяти: следующую попытку решатель
    делает уже с ними; в итоговой дельте метки всех раундов, уроки последнего."""
    def block(ctx, ep, memory, **extra):
        local, attempt, helpful, harmful, last = snapshot(memory), ep, [], [], None
        for _ in range(n if ep.ok is False else 1):
            d = inner(ctx, attempt, local, **extra)
            if not d:
                break
            last = d
            count(local, d.helpful, d.harmful)
            helpful, harmful = helpful + d.helpful, harmful + d.harmful
            if attempt.ok:
                break
            r = ctx.retry(local, note(d))
            attempt = replace(ep, output=r.output, answer=r.answer, steps=r.steps, truncated=r.truncated, used=r.reported,
                              context=r.context, shown=r.shown, ok=ctx.task.check(r.answer, ep.target), group=[])
            if attempt.ok:
                break
        return last and Delta(lessons=last.lessons, helpful=helpful, harmful=harmful, info=last.info)
    return block


def per_step(inner, steps):
    """steps(ep) -> [(сводка шага, ошибка или None)]; inner вызывается с extra step, error, found."""
    def block(ctx, ep, memory, **extra):
        found = []
        for step, error in steps(ep):
            out = inner(ctx, ep, memory, **{**extra, "step": step, "error": error, "found": found})
            if out is not None:
                found.append(out)
        return found or None
    return block


def perspectives(inner):
    """Попытка в зачёт и попытки остальных перспектив из группы; результаты подряд."""
    def block(ctx, ep, memory, **extra):
        out = []
        for e in [ep, *(g for g in ep.group if g.perspective)]:
            out += inner(ctx, e, memory, **extra) or []
        return out or None
    return block


def best_of(inner, n, select, valid=lambda c, **extra: True):
    """n = 1: просто inner. Иначе n кандидатов при temperature 0.7, отбор valid, из двух и более
    выбирает select(ctx, ep, memory, candidates=..., **extra) -> индекс или None."""
    if n == 1:
        return inner

    def block(ctx, ep, memory, **extra):
        cands = [c for c in (inner(ctx, ep, memory, **{**extra, "temperature": 0.7}) for _ in range(n)) if c]
        cands = [c for c in cands if valid(c, **extra)]
        if len(cands) < 2:
            return cands[0] if cands else None
        i = select(ctx, ep, memory, **{**extra, "candidates": cands})
        return cands[i] if i is not None and 0 <= i < len(cands) else cands[0]
    return block


def each_attempt(inner):
    def block(ctx, ep, memory, **extra):
        return [(g, inner(ctx, g, memory, **extra)) for g in ep.group]
    return block


def log_gain(best, scores, eps=0.01):
    """log(best) - log(mean(scores)), оба снизу ограничены eps."""
    return math.log(max(best, eps)) - math.log(max(sum(scores) / len(scores), eps))


def future_gain(attempts, scores, best, eps=0.01):
    """Каждой записи, бывшей в промпте лучшей попытки (с повторами), прирост лучшего балла над средним
    по попыткам без этой записи; если таких попыток нет, записи ничего."""
    out = []
    for rid in attempts[best].shown:
        rest = [s for s, a in zip(scores, attempts) if rid not in a.shown]
        if rest:
            out.append((rid, log_gain(scores[best], rest, eps)))
    return out
