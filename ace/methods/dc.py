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
"""
from pathlib import Path

from .. import embed
from ..env import Sandbox
from ..feedback import Feedback
from ..inject import View
from ..loop import Method, Solver, swap
from ..update import Update

PROMPTS = Path(__file__).parent / "prompts"
EMPTY = "(empty)"

# 1. память

MEMORY = {"sheet": ("add", "edit")}
MEMORY_RS = {"pair": ("add",), "sheet": ("add", "edit")}

# 2. инжект

SYNTH = (PROMPTS / "dc_synth.txt").read_text()
TOP = 3
NOTE = ("Note: The input-output pairs listed below are taken from previous test cases and are meant to assist you in "
        "understanding potential solution strategies or tool usages. While they can offer insight and inspiration, they "
        "should not be blindly copied, as they may contain errors or may not fit your specific use case. Approach them "
        "with a critical mindset—analyze their logic, verify their correctness, and adapt them as needed. Your goal "
        "should be to develop a well-reasoned solution that best addresses the problem at hand.")


def cheatsheet(block):
    """Текст внутри <cheatsheet>; None, если блока нет (апстрим тогда оставляет старый)."""
    if "<cheatsheet>" not in block:
        return None
    return block.split("<cheatsheet>", 1)[1].strip().split("</cheatsheet>")[0].strip()


def sheet(memory):
    return memory.of("sheet")[0].text if memory.of("sheet") else EMPTY


def whole(model, memory, item):
    return View(sheet(memory))


def retrieved(memory, item):
    """Top-k прошлых пар в оформлении апстрима и их id."""
    pairs = memory.of("pair")
    if not pairs:
        return EMPTY, []
    sims = embed.embed([r.when for r in pairs]) @ embed.embed([item["context"]])[0]
    top = list(sims.argsort()[::-1][:TOP])
    text = f"### PREVIOUS SOLUTIONS (START)\n\n{NOTE}\n\n"
    for i, j in enumerate(top[::-1]):
        text += (f"#### Previous Input #{i + 1} (Similarity: {sims[j]:.2f}):\n\n{pairs[j].when}\n\n"
                 f"#### Model Solution to Previous Input  #{i + 1}:\n\n{pairs[j].text}\n---\n---\n\n")
    return text.strip() + "\n\n#### PREVIOUS SOLUTIONS (END)", [pairs[j].id for j in top]


def retrieval(model, memory, item):
    return View(*retrieved(memory, item))


def retrieve_synth(model, memory, item):
    pairs, ids = retrieved(memory, item)
    prompt = (SYNTH.replace("[[PREVIOUS_INPUT_OUTPUT_PAIRS]]", pairs).replace("[[NEXT_INPUT]]", item["context"])
              .replace("[[PREVIOUS_CHEATSHEET]]", sheet(memory)))
    new = cheatsheet(model.one("", prompt, max_tokens=2 * model.max_tokens).text)
    return View(new if new is not None else pairs, ids)


def history(model, memory, item):
    pairs = memory.of("pair")
    if not pairs:
        return View(EMPTY)
    text = "### PREVIOUS SOLUTIONS (START)\n\n"
    for i, r in enumerate(pairs):
        text += (f"#### Previous Input #{i + 1}:\n\n{r.when}\n\n"
                 f"#### Model Solution to Previous Input #{i + 1}:\n\n{r.text}\n---\n---\n\n")
    return View(text + "#### PREVIOUS SOLUTIONS (END)", [r.id for r in pairs])

# 4. обновление

CURATOR = (PROMPTS / "dc_curator.txt").read_text()


def reflect(ctx, ep, memory):
    prompt = (CURATOR.replace("[[QUESTION]]", ep.question).replace("[[MODEL_ANSWER]]", ep.output)
              .replace("[[PREVIOUS_CHEATSHEET]]", sheet(memory)))
    return cheatsheet(ctx.model.one("", prompt, max_tokens=2 * ctx.model.max_tokens).text)


def curate(ctx, memory, sheets):
    for s in sheets:
        memory.rewrite("sheet", s)


def remember(ctx, ep, memory):
    return ep


def store(keep_sheet=True):
    def curate(ctx, memory, episodes):
        for ep in episodes:
            memory.add(ep.output, kind="pair", when=ep.question)
            if keep_sheet:
                memory.rewrite("sheet", ep.context)
    return curate


dc = Method("dc", MEMORY, whole, Feedback("none"), Update(reflect, curate))
dc_code = swap(dc, "dc_code", solver=Solver(env=Sandbox()))
dc_rs = Method("dc_rs", MEMORY_RS, retrieve_synth, Feedback("none"), Update(remember, store()))
dc_retrieval = Method("dc_retrieval", MEMORY_RS, retrieval, Feedback("none"), Update(remember, store(keep_sheet=False)))
dc_history = Method("dc_history", MEMORY_RS, history, Feedback("none"), Update(remember, store(keep_sheet=False)))
