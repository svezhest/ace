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
from .. import bound, curate, inject, prompts, reflect
from ..feedback import Feedback
from ..loop import Method, Solver, swap
from ..memory import ALL, Kind, perspectives
from ..update import Update, ask, seq, when

P = {n: prompts.load(f"scope_{n}.txt") for n in (
    "error", "efficiency", "thoroughness", "selector", "classify", "analyze", "merge", "subsumed", "conflict")}

# 1. память

MEMORY = {"strategic": ALL, "tactical": Kind(("add", "delete"), per="task")}
PERSPECTIVES = ("efficiency", "thoroughness")
MEMORY_K2 = perspectives(MEMORY, PERSPECTIVES)

# 2. инжект

INTRO = "## Strategic Guidelines (Learned Best Practices):\nThese are high-confidence rules learned from previous tasks:\n\n"
DOMAINS_LAYOUT = inject.by_group(inject.dashed, header="### {}:", title=inject.titled)

streams = inject.concat(
    inject.show(("strategic",), layout=DOMAINS_LAYOUT, before=INTRO, head=""),
    inject.show(("tactical",), line=inject.prefixed("## Learned Guideline:\n"), sep="\n\n", head=""),
    sep="\n\n")

# 4. обновление

DOMAINS = ["tool_usage", "data_validation", "error_handling", "efficiency", "analysis_methodology", "safety", "general"]
LEVEL = {"low": 0.3, "medium": 0.6, "high": 0.9}
ACCEPT, STRATEGIC, PER_RUN, CAP, TARGET = 0.5, 0.85, 20, 10, 8

propose = ask(reflect.by_issue(P["error"], P, "thoroughness"), reflect.rule_fields, reflect.Proposal)
select = ask(P["selector"], reflect.selector_fields, reflect.Selection, parse=reflect.selected_index)


def rules(n=1):
    """n > 1: Best-of-N, n кандидатов при temperature 0.7 и селектор (в апстриме кандидаты от разных моделей)."""
    step = seq(reflect.best_of(propose, n, select, reflect.meaningful), reflect.rule_lesson(LEVEL))
    return seq(reflect.perspectives(reflect.per_step(step, reflect.agent_steps)), reflect.as_lessons)


optimizer = bound.rule_optimizer(P)

classify = ask(P["classify"], curate.classify_fields(DOMAINS, INTRO, DOMAINS_LAYOUT), curate.Classification,
               then=curate.settle(DOMAINS))
promote = when(curate.promotable(STRATEGIC), curate.promote(CAP, TARGET, optimizer))
settle = curate.per_lesson(seq(classify, curate.accepted(ACCEPT), curate.limit(PER_RUN, key=lambda g: g["perspective"]),
                               curate.add_tactical, promote))

scope = Method("scope", MEMORY, streams, Feedback("golden"), Update(rules(), settle))
scope_bo2 = swap(scope, "scope_bo2", reflect=rules(n=2))
scope_k2 = Method("scope_k2", MEMORY_K2, streams, Feedback("golden"), Update(rules(), settle), Solver(perspectives=PERSPECTIVES))
