"""Dynamic Cheatsheet (dynamic-cheatsheet: dynamic_cheatsheet/language_model.py, run_benchmark.py).
Промпты куратора и синтеза апстрима дословно в prompts/dc_*.txt.

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
from .. import curate as stages, inject, prompts, reflect
from ..env import Sandbox
from ..feedback import Feedback
from ..loop import Method, Solver, swap
from ..update import Delta, Update, ask

SYNTH, CURATOR = prompts.load("dc_synth.txt", "brackets"), prompts.load("dc_curator.txt", "brackets")
EMPTY = "(empty)"

# 1. память

MEMORY = {"sheet": ("add", "edit")}
MEMORY_RS = {"pair": ("add",), "sheet": ("add", "edit")}

# 2. инжект

TOP = 3
NOTE = ("Note: The input-output pairs listed below are taken from previous test cases and are meant to assist you in "
        "understanding potential solution strategies or tool usages. While they can offer insight and inspiration, they "
        "should not be blindly copied, as they may contain errors or may not fit your specific use case. Approach them "
        "with a critical mindset—analyze their logic, verify their correctness, and adapt them as needed. Your goal "
        "should be to develop a well-reasoned solution that best addresses the problem at hand.")


def cheatsheet(block):
    """Текст внутри <cheatsheet>; None, если блока нет (апстрим тогда оставляет старый)."""
    if not block or "<cheatsheet>" not in block:
        return None
    return block.split("<cheatsheet>", 1)[1].strip().split("</cheatsheet>")[0].strip()


def sheet(memory):
    return memory.of("sheet")[0].text if memory.of("sheet") else EMPTY


def pairs(scored):
    """Пары в оформлении апстрима. scored (retrieval): с пояснением, близостью, самая похожая последней;
    иначе (полная история) по порядку."""
    def layout(records):
        text = "### PREVIOUS SOLUTIONS (START)\n\n" + (f"{NOTE}\n\n" if scored else "")
        for i, r in enumerate(records[::-1] if scored else records):
            if scored:
                text += (f"#### Previous Input #{i + 1} (Similarity: {r.meta['score']:.2f}):\n\n{r.when}\n\n"
                         f"#### Model Solution to Previous Input  #{i + 1}:\n\n{r.text}\n---\n---\n\n")
            else:
                text += (f"#### Previous Input #{i + 1}:\n\n{r.when}\n\n"
                         f"#### Model Solution to Previous Input #{i + 1}:\n\n{r.text}\n---\n---\n\n")
        return (text.strip() + "\n\n" if scored else text) + "#### PREVIOUS SOLUTIONS (END)"
    return layout


whole = inject.show(("sheet",), line=inject.plain, empty=EMPTY)
retrieval = inject.show(("pair",), pick=inject.topk(TOP, key=lambda r: r.when), layout=pairs(scored=True), empty=EMPTY)
history = inject.show(("pair",), layout=pairs(scored=False), empty=EMPTY)
retrieve_synth = inject.synth(retrieval, SYNTH, lambda view, memory, item: {
    "PREVIOUS_INPUT_OUTPUT_PAIRS": view.text, "NEXT_INPUT": item["context"], "PREVIOUS_CHEATSHEET": sheet(memory)}, cheatsheet)

# 4. обновление

def new_sheet(out, *_, **__):
    s = cheatsheet(out)
    return Delta(lessons=[s]) if s is not None else None


curator = ask(CURATOR, lambda ctx, ep, memory, **_: {"QUESTION": ep.question, "MODEL_ANSWER": ep.output,
                                                     "PREVIOUS_CHEATSHEET": sheet(memory)}, tokens=2, then=new_sheet)
rewrite = stages.each(stages.rewrite("sheet", text=lambda d: d.lessons[0]))
pair = stages.remember("pair", text=lambda ep: ep.output, when=lambda ep: ep.question)
store = stages.each(pair, stages.rewrite("sheet", text=lambda ep: ep.context))

dc = Method("dc", MEMORY, whole, Feedback("none"), Update(curator, rewrite))
dc_code = swap(dc, "dc_code", solver=Solver(env=Sandbox()))
dc_rs = Method("dc_rs", MEMORY_RS, retrieve_synth, Feedback("none"), Update(reflect.keep, store))
dc_retrieval = Method("dc_retrieval", MEMORY_RS, retrieval, Feedback("none"), Update(reflect.keep, stages.each(pair)))
dc_history = Method("dc_history", MEMORY_RS, history, Feedback("none"), Update(reflect.keep, stages.each(pair)))
