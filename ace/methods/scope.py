"""SCOPE (SCOPE/scope: optimizer.py, synthesizer.py, strategic_store.py, memory_optimizer.py).
Промпты апстрима дословно в prompts/scope_*.txt.

    1 память      strategic: правила по доменам (group), в meta rationale и confidence;
                  tactical: правила текущей задачи, Kind(per="task") — цикл стирает их перед новой задачей
    2 инжект      concat(strategic по доменам, tactical); задача у нас решается одним прогоном агента,
                  поэтому tactical до решателя не доходят
    3 сигнал      шаг с ошибкой: сбой инструмента или неверный итог (с верным ответом, как в адаптере);
                  остальные шаги идут на анализ качества
    4 обновление  reflect: perspectives(per_step(best_of(ask))) — на шаге кандидат правила, confidence меткой
                  low/medium/high; curate: per_lesson(seq(классификатор, допуск, limit 20, tactical, в strategic));
                  в strategic при confidence >= 0.85 без дубля по словам; домен сверх 10 правил сжимает
                  оптимизатор до 8 (конфликты, поглощение, слияние, до двух проходов), остаток обрезается
    решатель      общий; scope_k2: у перспектив efficiency и thoroughness своя память, в зачёт лучшая
"""
from pydantic import BaseModel

from .. import curate as stages, inject, prompts, reflect as steps
from ..feedback import Feedback
from ..loop import Method, Solver, swap
from ..memory import ALL, Kind
from ..update import Delta, Update, ask, seq, when

P = {n: prompts.load(f"scope_{n}.txt") for n in (
    "error", "efficiency", "thoroughness", "selector", "classify", "analyze", "merge", "subsumed", "conflict")}

# 1. память

MEMORY = {"strategic": ALL, "tactical": Kind(("add", "delete"), per="task")}
PERSPECTIVES = ("efficiency", "thoroughness")
MEMORY_K2 = {f"{kind}:{p}": ops for p in PERSPECTIVES for kind, ops in MEMORY.items()}


def kind(base, perspective):
    return f"{base}:{perspective}" if perspective else base

# 2. инжект

INTRO = "## Strategic Guidelines (Learned Best Practices):\nThese are high-confidence rules learned from previous tasks:\n\n"
DOMAINS_LAYOUT = inject.by_group(inject.dashed, header="### {}:", title=lambda d: d.replace("_", " ").title())

streams = inject.concat(
    inject.show(("strategic",), layout=DOMAINS_LAYOUT, before=INTRO, head=""),
    inject.show(("tactical",), line=lambda r: f"## Learned Guideline:\n{r.text}", sep="\n\n", head=""),
    sep="\n\n")


def strategic_text(records):
    """Как get_strategic_rules_text апстрима: с пустой строки в начале."""
    return "\n" + INTRO + DOMAINS_LAYOUT(records) if records else ""

# 4. обновление

DOMAINS = ["tool_usage", "data_validation", "error_handling", "efficiency", "analysis_methodology", "safety", "general"]
LEVEL = {"low": 0.3, "medium": 0.6, "high": 0.9}
ACCEPT, STRATEGIC, PER_RUN, CAP, TARGET = 0.5, 0.85, 20, 10, 8


class Proposal(BaseModel):
    update_text: str = ""
    rationale: str = ""
    confidence: str = "medium"


class Selection(BaseModel):
    selected_index: int = 0


class Classification(BaseModel):
    is_duplicate: bool = False
    scope: str = "tactical"
    confidence: float | None = None
    domain: str = "general"


class Analysis(BaseModel):
    consolidation: list[list[int]] = []
    subsumption: list[list[int]] = []
    conflicts: list[list[int]] = []


class Rule(BaseModel):
    rule: str
    rationale: str = ""


class Subsumed(BaseModel):
    subsumed: bool = False


def summary(output="", tools="", observations=""):
    """Сводка шага, обрезанная как в апстриме по умолчанию (truncate_context=True)."""
    cut = lambda s, n: s[:n] + "..." if len(s) > n else s
    parts = [f"Model output: {cut(output, 200)}" if output else "", f"Tool calls: {cut(tools, 150)}" if tools else "",
             f"Observations: {cut(observations, 150)}" if observations else ""]
    return "\n".join(p for p in parts if p) or "(no step details)"


def steps_of(ep):
    """Шаги агента: вызовы инструментов, затем итоговый ответ. У шага сводка и ошибка (тип, сообщение) или None."""
    out = []
    for name, args, result in ep.steps:
        failed = "Traceback" in result or result.startswith("Error")
        out.append((summary(tools=f"{name} {args}", observations=result), ("ToolError", result[-500:]) if failed else None))
    error = None
    if ep.ok is False:
        error = ("IncorrectAnswer", f"Incorrect answer. Model answered '{ep.answer}'" + (f", expected '{ep.target}'." if ep.target else "."))
    elif ep.truncated:
        error = ("Truncated", "The output was cut at the token limit before the final answer.")
    seen = "" if ep.ok is None else f"Answer {'correct' if ep.ok else 'incorrect'}"
    out.append((summary(ep.output, observations=seen), error))
    return out


def context(ctx, ep):
    return dict(agent_name=f"{ctx.task.name}_agent", agent_role=ctx.task.system, task=ep.question,
                current_system_prompt=f"{ctx.task.system}\n\n{ep.context}".strip())


def synth_fields(ctx, ep, memory, step, error, found, **extra):
    rules = [r.text for r in memory.of(kind("tactical", ep.perspective))] + [g["text"] for g in found]
    fields = dict(context(ctx, ep), last_step_summary=step, applied_rules="\n".join(f"- {r}" for r in rules) or "(none)")
    return dict(fields, error_type=error[0], error_message=error[1]) if error else fields


def select_fields(ctx, ep, memory, step, error, candidates, **extra):
    text = "".join(f"\n[Candidate {i}]\nUpdate: {c.update_text}\nRationale: {c.rationale}\nConfidence: {c.confidence}\n"
                   for i, c in enumerate(candidates))
    details = f"Error Type: {error[0]}\nError Message: {error[1]}\n\nLast Step:\n{step}" if error else f"Step Details:\n{step}"
    return dict(context(ctx, ep), issue_type="error" if error else "quality", issue_details=details, candidates=text)


def meaningful(c, error=None, **extra):
    """В Best-of-N без ошибки пустые и «no improvement needed» кандидаты отбрасываются."""
    return bool(error) or bool(c.update_text.strip()) and c.update_text.strip().lower() not in ("no improvement needed", "none")


def as_lesson(ctx, ep, memory, prev, **extra):
    if not prev.update_text:
        return None
    return dict(perspective=ep.perspective, text=prev.update_text, rationale=prev.rationale,
                confidence=LEVEL.get(prev.confidence.lower(), 0.5))


def reflect(n=1):
    """n > 1: Best-of-N, n кандидатов при temperature 0.7 и селектор (в апстриме кандидаты от разных моделей)."""
    propose = ask(lambda ep, memory, error=None, **_: P["error"] if error else P[ep.perspective or "thoroughness"],
                  synth_fields, Proposal)
    select = ask(P["selector"], select_fields, Selection, then=lambda s, *_, **__: s.selected_index if s else None)
    per_step = steps.per_step(seq(steps.best_of(propose, n, select, meaningful), as_lesson), steps_of)
    return steps.seq(steps.perspectives(per_step), lambda ctx, ep, memory, prev, **_: Delta(lessons=prev))


def classify_fields(ctx, memory, g, **extra):
    strategic, tactical = memory.of(kind("strategic", g["perspective"])), memory.of(kind("tactical", g["perspective"]))
    rules = ("\n=== STRATEGIC RULES (Cross-task, persistent): ===\n" + (strategic_text(strategic) or "No strategic rules yet.")
             + "\n\n=== TACTICAL RULES (Current task only): ===\n"
             + ("".join(f"{i}. {r.text}\n" for i, r in enumerate(tactical, 1)) or "No tactical rules yet.\n"))
    return dict(allowed_domains=", ".join(DOMAINS), update_text=g["text"], rationale=g["rationale"],
                initial_confidence=g["confidence"], all_rules_context=rules)


def settle(c, ctx, memory, g, **extra):
    """Сбой классификатора: tactical с исходной confidence; домен вне списка -> general."""
    if not c:
        return Classification(confidence=g["confidence"])
    if c.confidence is None:
        c.confidence = g["confidence"]
    if c.scope == "strategic" and c.domain not in DOMAINS:
        c.domain = "general"
    return c


def add_tactical(ctx, memory, g, prev, **extra):
    memory.add(g["text"], kind("tactical", g["perspective"]))
    return prev


def promote(ctx, memory, g, prev, **extra):
    """add_strategic_rule: без дубля по словам, домен по убыванию confidence, сверх CAP — оптимизатор."""
    strategic = kind("strategic", g["perspective"])
    same = [r for r in memory.of(strategic) if r.group == prev.domain]
    if stages.duplicate_words(g["text"], [r.text for r in same]):
        return None
    rules = sorted([as_rule(r) for r in same] + [dict(rule=g["text"], rationale=g["rationale"], confidence=prev.confidence)],
                   key=lambda x: -x["confidence"])
    if len(rules) > CAP:
        rules = optimize_rules(ctx.model, rules, TARGET)[:CAP]
    put(memory, strategic, prev.domain, rules)
    return prev


curate = stages.per_lesson(seq(
    ask(P["classify"], classify_fields, Classification, then=settle),
    when(lambda ctx, memory, g, prev, **_: not prev.is_duplicate and prev.confidence >= ACCEPT, lambda ctx, memory, g, prev, **_: prev),
    stages.limit(PER_RUN, key=lambda g: g["perspective"]),
    add_tactical,
    when(lambda ctx, memory, g, prev, **_: prev.scope == "strategic" and prev.confidence >= STRATEGIC, promote)))


def as_rule(r):
    return dict(rule=r.text, rationale=r.meta.get("rationale", ""), confidence=r.meta.get("confidence", 0.85),
                when=r.when, helpful=r.helpful, harmful=r.harmful)


def put(memory, kind, domain, rules):
    for r in memory.of(kind):
        if r.group == domain:
            memory.drop(r.id)
    for x in rules:
        memory.add(x["rule"], kind, when=x.get("when", ""), helpful=x.get("helpful", 0), harmful=x.get("harmful", 0),
                   group=domain, meta=dict(rationale=x.get("rationale", ""), confidence=x.get("confidence", 0.85)))


def llm(model, prompt, output):
    return model.run("", prompt, output=output).output


def optimize_rules(model, rules, target, passes=2):
    """MemoryOptimizer: анализ, затем конфликты, поглощение, слияние; номера правил стабильны между проходами."""
    for i, x in enumerate(rules):
        x.setdefault("id", i)
    for _ in range(passes):
        if len(rules) <= target:
            break
        a = llm(model, P["analyze"].format(num_rules=len(rules), rules_text="".join(f"Rule {x['id']}: {x['rule']}\n" for x in rules)),
                Analysis) or Analysis()
        if not (a.conflicts or a.subsumption or a.consolidation):
            break
        rules = resolve(model, rules, a.conflicts)
        rules = prune(model, rules, a.subsumption)
        rules = consolidate(model, rules, a.consolidation)
    return rules


def resolve(model, rules, pairs):
    by_id, done, fixed = {x["id"]: x for x in rules}, set(), {}
    for pair in pairs:
        if len(pair) < 2 or pair[0] not in by_id or pair[1] not in by_id or pair[0] in done or pair[1] in done:
            continue
        a, b = by_id[pair[0]], by_id[pair[1]]
        r = llm(model, P["conflict"].format(idx1=a["id"], rule1_text=a["rule"], rule1_rationale=a["rationale"],
                                            idx2=b["id"], rule2_text=b["rule"], rule2_rationale=b["rationale"]), Rule)
        if r:
            done |= {a["id"], b["id"]}
            fixed[a["id"]] = dict(rule=r.rule, rationale=r.rationale, id=a["id"],
                                  confidence=max(a.get("confidence", 0.85), b.get("confidence", 0.85)))
    return [fixed.get(x["id"], x) for x in rules if x["id"] not in done or x["id"] in fixed]


def prune(model, rules, pairs):
    by_id, gone = {x["id"]: x for x in rules}, set()
    for pair in pairs:
        if len(pair) >= 2 and pair[0] in by_id and pair[1] in by_id:
            r = llm(model, P["subsumed"].format(general_rule=by_id[pair[0]]["rule"], specific_rule=by_id[pair[1]]["rule"]), Subsumed)
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
        r = llm(model, P["merge"].format(rules_text=text), Rule)
        if r:
            out.append(dict(rule=r.rule, rationale=r.rationale, id=parts[0]["id"],
                            confidence=max(x.get("confidence", 0.85) for x in parts)))
        else:
            out += parts
    return out


def optimize(kinds, cap=CAP, target=TARGET):
    """Оптимизатор SCOPE как ограничитель для других методов: вид (и домен) сверх cap записей сжимается до target."""
    def bound(ctx, memory, before):
        for k in kinds:
            for domain in dict.fromkeys(r.group for r in memory.of(k)):
                same = [r for r in memory.of(k) if r.group == domain]
                if len(same) > cap:
                    put(memory, k, domain, optimize_rules(ctx.model, [as_rule(r) for r in same], target)[:cap])
    return bound


scope = Method("scope", MEMORY, streams, Feedback("golden"), Update(reflect(), curate))
scope_bo2 = swap(scope, "scope_bo2", reflect=reflect(n=2))
scope_k2 = Method("scope_k2", MEMORY_K2, streams, Feedback("golden"), Update(reflect(), curate), Solver(perspectives=PERSPECTIVES))
