"""Стадия bound обновления: ограничение памяти после правки. bound(ctx, memory, before), before — снимок до правки.

    prune(test)                     удалить записи, для которых test(r) (ACE: вредных больше, чем полезных)
    budget(share)                   память в промпте не длиннее доли бюджета генерации (прототип)
    gate()                          правка остаётся, только если на val не хуже (прототип)
    merge_similar(threshold, merge) похожие по эмбеддингу записи сливаются в первую (ACE BulletpointAnalyzer)
    optimize(kinds, cap, target)    группа сверх cap записей сжимается LLM (SCOPE)
    best_by_val()                   в конце прохода память откатывается к лучшей по val (MCE)
    chain(*bounds)                  по очереди"""
import copy

from . import embed


def chain(*bounds):
    def bound(ctx, memory, before):
        for b in bounds:
            b(ctx, memory, before)
    return bound


def prune(test):
    def bound(ctx, memory, before):
        for r in list(memory.records):
            if test(r):
                memory.drop(r.id)
    return bound


def budget(share, max_tokens=4096):
    """Память в промпте занимает не больше share бюджета генерации. Первыми уходят слабые insight, потом procedure."""
    limit = share * max_tokens * 4                        # символов, грубо 4 на токен

    def bound(ctx, memory, before):
        weak = sorted(memory.of("insight", "procedure"), key=lambda r: (r.kind == "procedure", r.helpful - r.harmful))
        while len(ctx.render(memory)) > limit and weak:
            memory.drop(weak.pop(0).id)
    return bound


def gate():
    """Правка принимается, только если на val не хуже прежней памяти: не меньше верных и не больше обрывов.
    Если решатель увидит то же самое, проверять нечего."""
    def bound(ctx, memory, before):
        if ctx.render(memory) == ctx.render(before):
            return
        after, prev = ctx.evaluate(memory), ctx.evaluate(before)
        ok = sum(c for c, _ in after) >= sum(c for c, _ in prev) and sum(t for _, t in after) <= sum(t for _, t in prev)
        if not ok:
            memory.records = before.records
        ctx.gated.append(ok)
    return bound


def merge_similar(threshold, merge):
    """Группы по всем парам: к записи i все следующие с косинусом >= threshold, уже попавшие в группу
    пропускаются. merge(ctx, group) -> (текст, helpful, harmful) или None; группа сводится к первой записи."""
    def bound(ctx, memory, before):
        recs = list(memory.records)
        if len(recs) < 2:
            return
        vecs = embed.embed([r.text for r in recs])
        sims, seen = vecs @ vecs.T, set()
        for i in range(len(recs)):
            if i in seen:
                continue
            group = [i] + [j for j in range(i + 1, len(recs)) if sims[i][j] >= threshold]
            if len(group) == 1:
                continue
            seen.update(group)
            merged = merge(ctx, [recs[j] for j in group])
            first = recs[i]
            if merged:
                memory.edit(first.id, merged[0])
                first.helpful, first.harmful = merged[1], merged[2]
            for j in group[1:]:
                memory.drop(recs[j].id)
    return bound


def best_by_val(history_key="iterations"):
    """В конце прохода: val текущей памяти в историю, память — лучшая по val (строго больше, при равенстве
    ранняя). Первая запись истории — пустая память до обучения. История в ctx.state[history_key]."""
    def bound(ctx, memory, before):
        history = ctx.state.setdefault(history_key, [])
        if ctx.step != ctx.total:
            return
        current = history[-1]
        current["val"], current["memory"] = accuracy(ctx.evaluate(memory)), copy.deepcopy(memory)
        best = history[0]
        for h in history[1:]:
            if h["val"] > best["val"]:
                best = h
        memory.records = copy.deepcopy(best["memory"].records)
        memory.counter = max(memory.counter, best["memory"].counter)
    return bound


def accuracy(results):
    return sum(c for c, _ in results) / len(results) if results else 0.0
