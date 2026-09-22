"""SCOPE (SCOPE/scope: optimizer.py, synthesizer.py, strategic_store.py, memory_optimizer.py).
Промпты апстрима дословно в prompts/scope_*.txt.

    1 память      strategic: правила по доменам, у правила rationale и confidence;
                  tactical: правила, принятые в текущей задаче, после неё стираются
    2 инжект      strategic по доменам, затем tactical текущей задачи; задача у нас решается
                  одним прогоном агента, поэтому tactical до решателя не доходят
    3 сигнал      шаг с ошибкой: сбой инструмента или неверный итог (с верным ответом, как в адаптере);
                  остальные шаги идут на анализ качества
    4 обновление  на каждом шаге один кандидат правила, confidence меткой low/medium/high;
                  классификатор: дубль, scope, уточнённая confidence, домен; принимается при
                  confidence >= 0.5, не больше 20 за прогон (счётчик в апстриме не сбрасывается);
                  в strategic при confidence >= 0.85 и без дубля по словам; домен сверх 10 правил
                  LLM сжимает до 8 (конфликты, поглощение, слияние, до двух проходов), остаток обрезается
    решатель      общий; scope_k2: у перспектив efficiency и thoroughness своя память, в зачёт лучшая
"""
from pathlib import Path

from pydantic import BaseModel

from ..feedback import Feedback
from ..inject import View
from ..loop import Method, Solver, swap
from ..memory import ALL
from ..update import Update

P = {n: (Path(__file__).parent / "prompts" / f"scope_{n}.txt").read_text() for n in (
    "error", "efficiency", "thoroughness", "selector", "classify", "analyze", "merge", "subsumed", "conflict")}

# 1. память

MEMORY = {"strategic": ALL, "tactical": ("add", "delete")}
PERSPECTIVES = ("efficiency", "thoroughness")
MEMORY_K2 = {f"{kind}:{p}": ops for p in PERSPECTIVES for kind, ops in MEMORY.items()}


def kind(base, perspective):
    return f"{base}:{perspective}" if perspective else base

# 2. инжект


def streams(model, memory, item):
    p = item.get("perspective", "")
    strategic = memory.of(kind("strategic", p))
    tactical = [r for r in memory.of(kind("tactical", p)) if r.meta["task"] == item["context"]]
    text = strategic_text(strategic) + "".join(f"\n\n## Learned Guideline:\n{r.text}" for r in tactical)
    return View(text.strip(), [r.id for r in strategic + tactical], head="")


def strategic_text(records):
    if not records:
        return ""
    lines = ["\n## Strategic Guidelines (Learned Best Practices):", "These are high-confidence rules learned from previous tasks:"]
    for domain in dict.fromkeys(r.meta["domain"] for r in records):
        lines.append(f"\n### {domain.replace('_', ' ').title()}:")
        lines += [f"- {r.text}" for r in records if r.meta["domain"] == domain]
    return "\n".join(lines)

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


def ask(model, prompt, output):
    return model.run("", prompt, output=output).output


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


def reflect(n=1):
    """n > 1: Best-of-N, n кандидатов при temperature 0.7 и селектор (в апстриме кандидаты от разных моделей)."""
    def run(ctx, ep, memory):
        found = []
        for e in [ep, *(g for g in ep.group if g.perspective)]:
            applied = [r.text for r in memory.of(kind("tactical", e.perspective)) if r.meta["task"] == ep.question]
            fields = dict(agent_name=f"{ctx.task.name}_agent", agent_role=ctx.task.system, task=ep.question,
                          current_system_prompt=f"{ctx.task.system}\n\n{e.context}".strip())
            for step, error in steps_of(e):
                rules = applied + [g["text"] for g in found if g["perspective"] == e.perspective]
                fields.update(last_step_summary=step, applied_rules="\n".join(f"- {r}" for r in rules) or "(none)")
                if error:
                    prompt = P["error"].format(error_type=error[0], error_message=error[1], **fields)
                else:
                    prompt = P[e.perspective or "thoroughness"].format(**fields)
                g = synthesize(ctx.model, prompt, n, error, fields, step)
                if g and g.update_text:
                    found.append(dict(perspective=e.perspective, task=ep.question, text=g.update_text,
                                      rationale=g.rationale, confidence=LEVEL.get(g.confidence.lower(), 0.5)))
        return found or None
    return run


def synthesize(model, prompt, n, error, fields, step):
    if n == 1:
        return ask(model, prompt, Proposal)
    cands = [c for c in (model.run("", prompt, output=Proposal, temperature=0.7).output for _ in range(n)) if c]
    if not error:
        cands = [c for c in cands if c.update_text.strip() and c.update_text.strip().lower() not in ("no improvement needed", "none")]
    if len(cands) < 2:
        return cands[0] if cands else None
    text = "".join(f"\n[Candidate {i}]\nUpdate: {c.update_text}\nRationale: {c.rationale}\nConfidence: {c.confidence}\n"
                   for i, c in enumerate(cands))
    details = f"Error Type: {error[0]}\nError Message: {error[1]}\n\nLast Step:\n{step}" if error else f"Step Details:\n{step}"
    s = ask(model, P["selector"].format(issue_type="error" if error else "quality", issue_details=details, candidates=text,
                                        **{k: fields[k] for k in ("agent_name", "agent_role", "task", "current_system_prompt")}), Selection)
    return cands[s.selected_index] if s and 0 <= s.selected_index < len(cands) else cands[0]


def curate(ctx, memory, deltas):
    for found in deltas:
        for g in found:
            tactical, strategic = kind("tactical", g["perspective"]), kind("strategic", g["perspective"])
            for r in memory.of(tactical):
                if r.meta["task"] != g["task"]:
                    memory.drop(r.id)
            c = classify(ctx.model, g, memory.of(strategic), [r.text for r in memory.of(tactical)])
            accepted = ctx.state.get("accepted" + g["perspective"], 0)
            if c.is_duplicate or accepted >= PER_RUN or c.confidence < ACCEPT:
                continue
            ctx.state["accepted" + g["perspective"]] = accepted + 1
            memory.add(g["text"], tactical, meta=dict(task=g["task"]))
            if c.scope == "strategic" and c.confidence >= STRATEGIC:
                promote(ctx.model, memory, strategic, dict(rule=g["text"], rationale=g["rationale"], confidence=c.confidence), c.domain)


def classify(model, g, strategic, tactical):
    context = ("\n=== STRATEGIC RULES (Cross-task, persistent): ===\n" + (strategic_text(strategic) or "No strategic rules yet.")
               + "\n\n=== TACTICAL RULES (Current task only): ===\n"
               + ("".join(f"{i}. {t}\n" for i, t in enumerate(tactical, 1)) or "No tactical rules yet.\n"))
    c = ask(model, P["classify"].format(allowed_domains=", ".join(DOMAINS), update_text=g["text"], rationale=g["rationale"],
                                        initial_confidence=g["confidence"], all_rules_context=context), Classification)
    if not c:
        return Classification(confidence=g["confidence"])
    if c.confidence is None:
        c.confidence = g["confidence"]
    if c.scope == "strategic" and c.domain not in DOMAINS:
        c.domain = "general"
    return c


def duplicate(text, rules):
    """Дубль в strategic_store: подстрока или общих слов больше 70%."""
    new = text.strip().lower()
    for r in rules:
        old = r.text.strip().lower()
        if new in old or old in new:
            return True
        a, b = set(new.split()), set(old.split())
        if a and b and len(a & b) / max(len(a), len(b)) > 0.7:
            return True
    return False


def promote(model, memory, strategic, rule, domain):
    same = [r for r in memory.of(strategic) if r.meta.get("domain", "") == domain]
    if duplicate(rule["rule"], same):
        return
    rules = sorted([as_rule(r) for r in same] + [rule], key=lambda x: -x["confidence"])
    if len(rules) > CAP:
        rules = optimize_rules(model, rules, TARGET)[:CAP]
    put(memory, strategic, domain, rules)


def as_rule(r):
    return dict(rule=r.text, rationale=r.meta.get("rationale", ""), confidence=r.meta.get("confidence", 0.85),
                when=r.when, helpful=r.helpful, harmful=r.harmful)


def put(memory, kind, domain, rules):
    for r in memory.of(kind):
        if r.meta.get("domain", "") == domain:
            memory.drop(r.id)
    for x in rules:
        memory.add(x["rule"], kind, when=x.get("when", ""), helpful=x.get("helpful", 0), harmful=x.get("harmful", 0),
                   meta=dict(domain=domain, rationale=x.get("rationale", ""), confidence=x.get("confidence", 0.85)))


def optimize_rules(model, rules, target, passes=2):
    """MemoryOptimizer: анализ, затем конфликты, поглощение, слияние; номера правил стабильны между проходами."""
    for i, x in enumerate(rules):
        x.setdefault("id", i)
    for _ in range(passes):
        if len(rules) <= target:
            break
        a = ask(model, P["analyze"].format(num_rules=len(rules), rules_text="".join(f"Rule {x['id']}: {x['rule']}\n" for x in rules)),
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
        r = ask(model, P["conflict"].format(idx1=a["id"], rule1_text=a["rule"], rule1_rationale=a["rationale"],
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
            r = ask(model, P["subsumed"].format(general_rule=by_id[pair[0]]["rule"], specific_rule=by_id[pair[1]]["rule"]), Subsumed)
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
        r = ask(model, P["merge"].format(rules_text=text), Rule)
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
            for domain in dict.fromkeys(r.meta.get("domain", "") for r in memory.of(k)):
                same = [r for r in memory.of(k) if r.meta.get("domain", "") == domain]
                if len(same) > cap:
                    put(memory, k, domain, optimize_rules(ctx.model, [as_rule(r) for r in same], target)[:cap])
    return bound


scope = Method("scope", MEMORY, streams, Feedback("golden"), Update(reflect(), curate))
scope_bo2 = swap(scope, "scope_bo2", reflect=reflect(n=2))
scope_k2 = Method("scope_k2", MEMORY_K2, streams, Feedback("golden"), Update(reflect(), curate), Solver(perspectives=PERSPECTIVES))
