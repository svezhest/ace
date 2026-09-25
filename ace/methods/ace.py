"""ACE (Agentic Context Engineering). Два варианта из одних блоков.

ace — вариант стенда, основа цепочки абляций:
    1 память      пункты (Bullet) со всеми операциями и счётчиками helpful / harmful
    2 инжект      все пункты «[id] текст»
    3 сигнал      верный ответ
    4 обновление  reflect: ask -> уроки и метки пунктов; curate: счётчики, затем пункты правит агент файловыми
                  инструментами (или одной схемой операций, или перезаписью); bound: prune вредных

ace_exact — как в апстриме (ace/ace/ace.py, core/, playbook_utils.py; промпты ace/prompts/ace_*.j2 дословно):
    1 память      playbook: пункты по 7 разделам (поле section), только добавляются
    2 инжект      весь playbook по разделам, строка «[id] helpful=X harmful=Y :: текст»
    3 сигнал      верный ответ и id пунктов, названных решателем (строка USED вместо bullet_ids)
    4 обновление  reflect: rounds(ask) — при неверном ответе до 3 раундов «рефлексия -> счётчики -> новая
                  попытка»; curate: счётчики, затем куратор (последняя рефлексия, вопрос, бюджет токенов,
                  статистика playbook) отвечает ADD с разделом
    Решение после куратора в апстриме только для отчёта: не делаем.
    ace_exact_dedup: bound merge_similar — BulletpointAnalyzer (в апстриме выключен).
"""
from .. import bound, curate, inject, prompts, reflect
from ..feedback import Feedback
from ..loop import Method, swap
from ..memory import Bullet, Kind
from ..update import Update, ask

# ace

MEMORY = {"bullet": Kind(Bullet)}

REFLECT = prompts.load("ace_stand_reflect")
CURATE = {m: prompts.load(f"ace_stand_curate{s}") for m, s in (("tools", ""), ("json", "_json"), ("rewrite", "_rewrite"))}
REFLECTOR, CURATOR = prompts.text("reflector_system"), prompts.text("curator_system")

reflect_json = ask(REFLECT, reflect.lesson_fields(""), reflect.Reflection, system=REFLECTOR,
                   then=reflect.labeled_lessons())
reflect_text = ask(REFLECT, reflect.lesson_fields(prompts.text("reflect_free_form")), system=REFLECTOR, then=reflect.free_lessons())

# куратор: файловые инструменты по одной операции, все операции одной схемой или вся память заново
merge_tools = curate.tools(CURATE["tools"], curate.lessons_fields(curate.files_view), curate.memory_files, rounds=6)
merge_json = ask(CURATE["json"], curate.lessons_fields(curate.text_view), curate.Ops, system=CURATOR,
                 then=curate.apply_ops(curate.op_dicts, missing="skip"))
merge_rewrite = ask(CURATE["rewrite"], curate.lessons_fields(curate.text_view), system=CURATOR,
                    then=curate.rewrite_first)
curate_tools, curate_json, curate_rewrite = (curate.each(curate.count, curate.admit(curate.has_lessons, m))
                                             for m in (merge_tools, merge_json, merge_rewrite))

ace = Method("ace", MEMORY, inject.full(), Feedback("golden"),
             Update(reflect_json, curate_tools, bound.prune(bound.more_harmful(3))))

# ace_exact

P = {n: prompts.load(f"ace_{n}") for n in ("reflector", "reflector_nogt", "curator", "curator_nogt", "merge")}
SECTIONS = ["STRATEGIES & INSIGHTS", "FORMULAS & CALCULATIONS", "CODE SNIPPETS & TEMPLATES", "COMMON MISTAKES TO AVOID",
            "PROBLEM-SOLVING HEURISTICS", "CONTEXT CLUES & INDICATORS", "OTHERS"]
ROUNDS, TOKEN_BUDGET = 3, 80000

PLAYBOOK = {"bullet": Kind(Bullet, ("add",))}
LAYOUT = inject.sections(SECTIONS)

diagnosis = ask(reflect.by_label(P["reflector"], P["reflector_nogt"]), reflect.diagnosis_fields, reflect.Diagnosis,
                then=reflect.diagnosis_delta)
curator = ask(curate.by_label(P["curator"], P["curator_nogt"]), curate.playbook_fields(SECTIONS, TOKEN_BUDGET, LAYOUT),
              curate.Curation, then=curate.add(curate.additions, text=lambda op: op.content, section=curate.in_section(SECTIONS)))

ace_exact = Method("ace_exact", PLAYBOOK, inject.show(layout=LAYOUT), Feedback("golden", usage="self"),
                   Update(reflect.rounds(diagnosis, ROUNDS), curate.each(curate.count, curator), needs_usage=True))
# порог апстрима 0.90 подобран под all-mpnet; у BGE-M3 косинусы ниже
ace_exact_dedup = swap(ace_exact, "ace_exact_dedup", memory={"bullet": Kind(Bullet, ("add", "edit", "delete"))},
                       bound=bound.merge_similar(0.85, bound.merge_counted(P["merge"])))
