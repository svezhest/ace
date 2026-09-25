"""Dynamic Cheatsheet (dynamic-cheatsheet: dynamic_cheatsheet/language_model.py, run_benchmark.py).
Промпты куратора и синтеза апстрима дословно в ace/prompts/dc_*.j2.

DC-Cu
    1 память      один текст (cheatsheet), в начале "(empty)"
    2 инжект      весь текст
    3 сигнал      без метки
    4 обновление  один вызов после задачи переписывает текст целиком; без блока <cheatsheet> остаётся старый

DC-RS
    1 память      пары (вопрос, решение) и последний синтезированный cheatsheet
    2 инжект      top-3 похожих прошлых пары (BGE-M3; в апстриме готовые эмбеддинги из embeddings/<task>.csv)
                  оформляются как PREVIOUS SOLUTIONS с близостью, самая похожая последней; из них
                  и прошлого cheatsheet синтезируется новый, и на первом примере тоже (пары "(empty)");
                  без блока <cheatsheet> решатель получает сами пары
    3 сигнал      без метки
    4 обновление  пара добавляется, синтезированный cheatsheet сохраняется

Контроли апстрима: dc_retrieval (пары без синтеза), dc_history (все прошлые пары подряд).
Исполнение кода в апстриме включено по умолчанию (execute_python_code=True): вариант dc_code с Sandbox.
Куратор и синтез в апстриме пишут до 2 * max_tokens.

Сборка: dc — show(sheet) + reflect ask(curator) + curate rewrite; dc_rs — synth(show(pair, topk, пары)) +
reflect keep + curate remember(пара) и rewrite(показанный cheatsheet).
"""
from .. import curate, inject, parse, prompts, reflect
from ..env import Sandbox
from ..feedback import Feedback
from ..loop import Method, Solver, swap
from ..memory import Kind, Note, Pair
from ..update import Update, ask

SYNTH, CURATOR = prompts.load("dc_synth"), prompts.load("dc_curator")
NOTE = prompts.text("dc_note")
EMPTY = "(empty)"
CHEATSHEET = parse.opened("cheatsheet")

# 1. память

MEMORY = {"sheet": Kind(Note, ("add", "edit"))}
MEMORY_RS = {"pair": Kind(Pair, ("add",)), "sheet": Kind(Note, ("add", "edit"))}

# 2. инжект

TOP = 3
TOKENS = 2                  # куратор и синтез пишут до 2 * max_tokens, как в апстриме

whole = inject.show(("sheet",), line=inject.plain, empty=EMPTY)
retrieval = inject.show(("pair",), pick=inject.topk(TOP, key=lambda r: r.question), layout=inject.pairs(scored=True, note=NOTE), empty=EMPTY)
history = inject.show(("pair",), layout=inject.pairs(scored=False), empty=EMPTY)
retrieve_synth = inject.synth(retrieval, SYNTH, inject.pairs_and_sheet("sheet", EMPTY), CHEATSHEET, max_tokens=TOKENS)

# 4. обновление

curator = ask(CURATOR, reflect.answer_and_sheet("sheet", EMPTY), tokens=TOKENS, parse=CHEATSHEET, then=reflect.rewritten)
rewrite = curate.each(curate.rewrite("sheet", text=lambda d: d.lessons[0]))
pair = curate.remember("pair", text=lambda ep: ep.output, question=lambda ep: ep.question)
store = curate.each(pair, curate.rewrite("sheet", text=lambda ep: ep.context))

dc = Method("dc", MEMORY, whole, Feedback("none"), Update(curator, rewrite))
dc_code = swap(dc, "dc_code", solver=Solver(env=Sandbox()))
dc_rs = Method("dc_rs", MEMORY_RS, retrieve_synth, Feedback("none"), Update(reflect.keep, store))
dc_retrieval = Method("dc_retrieval", MEMORY_RS, retrieval, Feedback("none"), Update(reflect.keep, curate.each(pair)))
dc_history = Method("dc_history", MEMORY_RS, history, Feedback("none"), Update(reflect.keep, curate.each(pair)))
