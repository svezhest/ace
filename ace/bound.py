"""Ограничители роста памяти, общие для методов. Сигнатура bound(model, memory, task, method)."""
import copy

from . import loop


def budget(share, max_tokens=4096):
    """Память занимает не больше share бюджета генерации. Первыми уходят слабые insight'ы, потом procedure."""
    limit = share * max_tokens * 4                        # символов, грубо 4 на токен

    def bound(model, memory, task, method):
        weak = sorted((r for r in memory.records if r.kind in ("insight", "procedure")),
                      key=lambda r: (r.kind == "procedure", r.helpful - r.harmful))
        while len(method.inject(memory)) > limit and weak:
            memory.drop(weak.pop(0).id)
    return bound


def gate(n=10):
    """Дельта принимается, только если на val-батче не хуже прежней памяти: не меньше верных и не больше обрывов."""
    def bound(model, memory, task, method):
        items = task.load("val")[:n]
        score = lambda: [(t.correct, t.truncated) for t in (loop.solve(model, task, memory, method, it) for it in items)]
        new, after = memory.records, score()
        memory.records = memory.before
        before = score()
        ok = sum(c for c, _ in after) >= sum(c for c, _ in before) and sum(t for _, t in after) <= sum(t for _, t in before)
        memory.records = new if ok else memory.before
        memory.gated.append(ok)
    return bound


def chain(*bounds):
    def bound(*args):
        for b in bounds:
            b(*args)
    return bound


def dedup(threshold=0.75, max_records=None):
    """Grow-and-refine из ACE: новая запись, близкая по эмбеддингу к старой (косинус >= threshold;
    на BGE-M3 перефразировки дают 0.74-0.81, разные уроки 0.4-0.67),
    сливается с ней: счётчики складываются, остаётся старая. При max_records лишние уходят по порядку добавления."""
    from . import embed

    def bound(model, memory, task, method):
        before = {r.id for r in memory.before}
        old = [r for r in memory.records if r.id in before]
        new = [r for r in memory.records if r.id not in before]
        if old and new:
            sims = embed.embed([r.text for r in new]) @ embed.embed([r.text for r in old]).T
            for i, r in enumerate(new):
                j = int(sims[i].argmax())
                if sims[i][j] >= threshold:
                    old[j].helpful += r.helpful
                    old[j].harmful += r.harmful
                    memory.drop(r.id)
        if max_records:
            for r in memory.records[:-max_records]:
                memory.drop(r.id)
    return bound
