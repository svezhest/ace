"""Стадия bound обновления: ограничение памяти после правки. bound(ctx, memory, before), before — снимок до правки.

    prune(test)                     удалить записи, для которых test(r); more_harmful — ACE стенда
    budget(share)                   память в промпте не длиннее доли бюджета генерации (прототип)
    gate()                          правка остаётся, только если на val не хуже (прототип)
    merge_similar(threshold, merge) похожие по эмбеддингу записи сливаются в первую;
                                    merge_counted — слияние моделью (ACE BulletpointAnalyzer)
    optimize(kinds, optimizer, ...) группа сверх cap записей сжимается до target; rule_optimizer — MemoryOptimizer
                                    SCOPE (конфликты, поглощение, слияние); as_rule, put_rules — записи <-> правила
    best_by_val()                   в конце прохода память откатывается к лучшей по val (MCE)
    chain(*bounds)                  по очереди"""
import copy

from pydantic import BaseModel

from . import embed, parse
from .inject import counted


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


def more_harmful(n):
    """Вредных меток не меньше n и больше, чем полезных."""
    return lambda r: r.harmful >= n and r.harmful > r.helpful


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


def merge_counted(prompt, temperature=0.3):
    """Слияние группы моделью по prompt; ответ «[id] helpful=N harmful=M :: текст» с id первой записи."""
    def merge(ctx, group):
        first = group[0]
        helpful, harmful = sum(r.helpful for r in group), sum(r.harmful for r in group)
        out = ctx.model.one("", prompt.fill(dict(bullets="\n".join(f"{k + 1}. {counted(r)}" for k, r in enumerate(group)),
                                                 id=first.id, helpful=helpful, harmful=harmful)), temperature=temperature).output
        return parse.counted_line(first.id)(out)
    return merge

# оптимизатор правил SCOPE; правило — словарь rule, rationale, confidence, id


class Analysis(BaseModel):
    consolidation: list[list[int]] = []
    subsumption: list[list[int]] = []
    conflicts: list[list[int]] = []


class Rule(BaseModel):
    rule: str
    rationale: str = ""


class Subsumed(BaseModel):
    subsumed: bool = False


def as_rule(r):
    return dict(rule=r.text, rationale=r.meta.get("rationale", ""), confidence=r.meta.get("confidence", 0.85),
                when=r.when, helpful=r.helpful, harmful=r.harmful)


def put_rules(memory, kind, group, rules):
    """Записи вида kind в группе group заменяются правилами."""
    for r in memory.of(kind):
        if r.group == group:
            memory.drop(r.id)
    for x in rules:
        memory.add(x["rule"], kind, when=x.get("when", ""), helpful=x.get("helpful", 0), harmful=x.get("harmful", 0),
                   group=group, meta=dict(rationale=x.get("rationale", ""), confidence=x.get("confidence", 0.85)))


def rule_optimizer(prompts, passes=2):
    """prompts: analyze, conflict, subsumed, merge. -> optimize(model, rules, target): анализ, затем конфликты,
    поглощение, слияние, до passes проходов; номера правил стабильны между проходами."""
    llm = lambda model, name, fields, output: model.run("", prompts[name].fill(fields), output=output).output

    def resolve(model, rules, pairs):
        by_id, done, fixed = {x["id"]: x for x in rules}, set(), {}
        for pair in pairs:
            if len(pair) < 2 or pair[0] not in by_id or pair[1] not in by_id or pair[0] in done or pair[1] in done:
                continue
            a, b = by_id[pair[0]], by_id[pair[1]]
            r = llm(model, "conflict", dict(idx1=a["id"], rule1_text=a["rule"], rule1_rationale=a["rationale"],
                                            idx2=b["id"], rule2_text=b["rule"], rule2_rationale=b["rationale"]), Rule)
            if r:
                done |= {a["id"], b["id"]}
                fixed[a["id"]] = dict(rule=r.rule, rationale=r.rationale, id=a["id"],
                                      confidence=max(a.get("confidence", 0.85), b.get("confidence", 0.85)))
        return [fixed.get(x["id"], x) for x in rules if x["id"] not in done or x["id"] in fixed]

    def prune_subsumed(model, rules, pairs):
        by_id, gone = {x["id"]: x for x in rules}, set()
        for pair in pairs:
            if len(pair) >= 2 and pair[0] in by_id and pair[1] in by_id:
                r = llm(model, "subsumed", dict(general_rule=by_id[pair[0]]["rule"], specific_rule=by_id[pair[1]]["rule"]), Subsumed)
                if r and r.subsumed:
                    gone.add(pair[1])
        return [x for x in rules if x["id"] not in gone]

    def consolidate(model, rules, groups):
        by_id = {x["id"]: x for x in rules}
        merged = {i for g in groups for i in g}
        out = [x for x in rules if x["id"] not in merged]
        for group in groups:
            parts = [by_id[i] for i in group if i in by_id]
            if len(group) < 2 or not parts:
                out += parts
                continue
            text = "".join(f"\nRule {x['id']}:\n  Text: {x['rule']}\n  Rationale: {x['rationale']}\n" for x in parts)
            r = llm(model, "merge", dict(rules_text=text), Rule)
            if r:
                out.append(dict(rule=r.rule, rationale=r.rationale, id=parts[0]["id"],
                                confidence=max(x.get("confidence", 0.85) for x in parts)))
            else:
                out += parts
        return out

    def optimize(model, rules, target):
        for i, x in enumerate(rules):
            x.setdefault("id", i)
        for _ in range(passes):
            if len(rules) <= target:
                break
            a = llm(model, "analyze", dict(num_rules=len(rules), rules_text="".join(f"Rule {x['id']}: {x['rule']}\n" for x in rules)),
                    Analysis) or Analysis()
            if not (a.conflicts or a.subsumption or a.consolidation):
                break
            rules = resolve(model, rules, a.conflicts)
            rules = prune_subsumed(model, rules, a.subsumption)
            rules = consolidate(model, rules, a.consolidation)
        return rules
    return optimize


def optimize(kinds, optimizer, cap, target):
    """Вид (и группа) сверх cap записей сжимается optimizer до target, остаток обрезается до cap."""
    def bound(ctx, memory, before):
        for k in kinds:
            for group in dict.fromkeys(r.group for r in memory.of(k)):
                same = [r for r in memory.of(k) if r.group == group]
                if len(same) > cap:
                    put_rules(memory, k, group, optimizer(ctx.model, [as_rule(r) for r in same], target)[:cap])
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
