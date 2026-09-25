"""SCOPE (SCOPE/scope: optimizer.py, synthesizer.py, strategic_store.py, memory_optimizer.py).
Промпты апстрима дословно в ace/prompts/scope_*.j2.

    1 память      strategic (Rule): правила по доменам, rationale и confidence;
                  tactical: правила текущей задачи (принятые в ней), Kind(per="task") — цикл стирает их перед новой
    2 инжект      при запуске strategic по доменам; после каждого шага с инструментом к системному промпту
                  дописываются tactical («## Learned Guideline:», как в апстриме)
    3 сигнал      шаг с ошибкой: сбой инструмента или неверный итог (с верным ответом, как в адаптере);
                  остальные шаги идут на анализ качества
    4 обновление  событие шага с инструментом: правило сразу (at_once), со следующего шага оно в промпте;
                  событие задачи: правило по итоговому шагу. Правило: best_of(ask) — кандидат, confidence меткой
                  low/medium/high; curate: per_lesson(seq(классификатор, допуск, limit 20, tactical, в strategic));
                  в strategic при confidence >= 0.85 без дубля по словам; домен сверх 10 правил сжимает
                  оптимизатор до 8 (конфликты, поглощение, слияние, до двух проходов), остаток обрезается
    решатель      общий (без инструментов шаг один — итоговый); scope_code — с исполнением python, как агенты
                  апстрима с инструментами; scope_k2: у перспектив efficiency и thoroughness своя память, в зачёт лучшая
"""
from .. import bound, curate, inject, prompts, reflect
from ..env import Sandbox
from ..feedback import Feedback
from ..loop import Method, Solver, swap
from ..memory import Kind, Note, Rule, perspectives
from ..update import Update, ask, at_once, seq, when

P = {n: prompts.load(f"scope_{n}") for n in (
    "error", "efficiency", "thoroughness", "selector", "classify", "analyze", "merge", "subsumed", "conflict")}

# 1. память

MEMORY = {"strategic": Kind(Rule), "tactical": Kind(Note, ("add", "delete"), per="task")}
PERSPECTIVES = ("efficiency", "thoroughness")
MEMORY_K2 = perspectives(MEMORY, PERSPECTIVES)

# 2. инжект

INTRO = prompts.text("scope_strategic_intro")
DOMAINS_LAYOUT = inject.by_group(inject.dashed, "domain", header="### {}:", title=inject.titled)

tactical = inject.show(("tactical",), line=inject.prefixed(prompts.text("scope_guideline")), sep="\n\n", head="")
streams = inject.hooked(inject.concat(inject.show(("strategic",), layout=DOMAINS_LAYOUT, before=INTRO, head=""), tactical,
                                      sep="\n\n"), tactical)

# 4. обновление

DOMAINS = ["tool_usage", "data_validation", "error_handling", "efficiency", "analysis_methodology", "safety", "general"]
LEVEL = {"low": 0.3, "medium": 0.6, "high": 0.9}
ACCEPT, STRATEGIC, PER_RUN, CAP, TARGET = 0.5, 0.85, 20, 10, 8

propose = ask(reflect.by_issue(P["error"], P, "thoroughness"), reflect.rule_fields, reflect.Proposal)
select = ask(P["selector"], reflect.selector_fields, reflect.Selection, parse=reflect.selected_index)
optimizer = bound.rule_optimizer(P)

classify = ask(P["classify"], curate.classify_fields(DOMAINS, INTRO, DOMAINS_LAYOUT), curate.Classification,
               then=curate.settle(DOMAINS))
promote = when(curate.promotable(STRATEGIC), curate.promote(CAP, TARGET, optimizer))
settle = curate.per_lesson(seq(classify, curate.accepted(ACCEPT), curate.limit(PER_RUN, key=lambda g: g["perspective"]),
                               curate.add_tactical, promote))


def rules(n=1):
    """Обновление SCOPE: правило на шаге с инструментом сразу, на итоговом шаге — после задачи.
    n > 1: Best-of-N, n кандидатов при temperature 0.7 и селектор (в апстриме кандидаты от разных моделей)."""
    rule = seq(reflect.best_of(propose, n, select, reflect.meaningful), reflect.rule_lesson(LEVEL))
    return Update(seq(reflect.perspectives(reflect.on_answer(rule)), reflect.as_lessons), settle,
                  step=at_once(reflect.on_tool(rule), settle))


scope = Method("scope", MEMORY, streams, Feedback("golden"), rules())
scope_code = swap(scope, "scope_code", solver=Solver(env=Sandbox()))
scope_bo2 = swap(scope, "scope_bo2", update=rules(n=2))
scope_k2 = Method("scope_k2", MEMORY_K2, streams, Feedback("golden"), rules(), Solver(perspectives=PERSPECTIVES))
