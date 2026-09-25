"""Прототип.

    1 память      типизированные записи (Entry: условие when и счётчики) с политикой по типу:
                  constraint  только add и narrow
                  procedure   любые операции
                  insight     любые операции, первый кандидат на удаление
                  episode     только add; скрытый вид: решателю не показывается, это provenance
    2 инжект      constraint целиком в промпте, procedure и insight каталогом, тело по read(path)
    3 сигнал      верный ответ; что решатель прочёл, записывает среда (read)
    4 обновление  рефлексия только по прочитанным записям -> куратор операциями add / patch / narrow / merge
                  -> бюджет доли промпта
"""
from .. import bound, curate, inject, prompts, reflect
from ..feedback import Feedback
from ..loop import Method
from ..memory import ALL, Entry, Kind
from ..update import Update, ask

# 1. память

MEMORY = {"constraint": Kind(Entry, ("add", "narrow")), "procedure": Kind(Entry, ALL), "insight": Kind(Entry, ALL),
          "episode": Kind(Entry, ("add",), private=True, ids="e")}

# 2. инжект

INJECT = inject.catalog(always=("constraint",), listed=("procedure", "insight"))

# 4. обновление

REFLECT = prompts.load("proto_reflect")
CURATE = {m: prompts.load(f"proto_curate{s}") for m, s in (("tools", ""), ("json", "_json"), ("rewrite", "_rewrite"))}
REFLECTOR, CURATOR = prompts.text("reflector_system"), prompts.text("curator_system")

reflect_json = ask(REFLECT, reflect.lesson_fields("", sees="used"), reflect.TypedReflection, system=REFLECTOR,
                   then=reflect.labeled_lessons(episode=True))
reflect_text = ask(REFLECT, reflect.lesson_fields(prompts.text("reflect_free_form"), sees="used"), system=REFLECTOR,
                   then=reflect.free_lessons(episode=True))

# куратор: по одной операции за вызов, все операции одной схемой или все записи заново; эпизоды не трогает никто
FIELDS = curate.lessons_fields(curate.entries_view)
merge_tools = curate.tools(CURATE["tools"], FIELDS, curate.memory_itself, rounds=4, toolset=curate.TYPED_TOOLS)
merge_json = ask(CURATE["json"], FIELDS, curate.TypedOps, system=CURATOR, then=curate.apply_typed)
merge_rewrite = ask(CURATE["rewrite"], FIELDS, curate.Entries, system=CURATOR, then=curate.replace_entries)
curate_tools, curate_json, curate_rewrite = (curate.each(curate.add_episode, curate.count, curate.admit(curate.has_lessons, m))
                                             for m in (merge_tools, merge_json, merge_rewrite))

proto = Method("proto", MEMORY, INJECT, Feedback("golden", usage="env"),
               Update(reflect_json, curate_tools, bound.budget(0.25), needs_usage=True))
