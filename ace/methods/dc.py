"""Dynamic Cheatsheet. Промпты куратора и синтеза взяты из апстрима как есть (prompts/).

DC-Cu
    1 память      один текст (cheatsheet)
    2 инжект      весь текст
    3 сигнал      без метки
    4 обновление  один вызов после задачи переписывает текст целиком

DC-RS
    1 память      пары (вопрос, решение) и последний синтезированный cheatsheet
    2 инжект      до решения достаём top-3 похожих пары (BGE-M3; в статье text-embedding-3-small)
                  и синтезируем из них cheatsheet под этот вопрос
    3 сигнал      без метки
    4 обновление  пара добавляется, синтезированный cheatsheet сохраняется
"""
from pathlib import Path

from .. import embed, inject
from ..feedback import Feedback
from ..inject import View
from ..loop import Method
from ..update import Update

PROMPTS = Path(__file__).parent / "prompts"

# 1. память

MEMORY = {"sheet": ("add", "edit")}
MEMORY_RS = {"pair": ("add",), "sheet": ("add", "edit")}

# 2. инжект

SYNTH = (PROMPTS / "dc_synth.txt").read_text()
TOP = 3


def cheatsheet(block):
    """Текст внутри <cheatsheet>; None, если блока нет (апстрим тогда оставляет старый)."""
    if "<cheatsheet>" not in block:
        return None
    return block.split("<cheatsheet>", 1)[1].split("</cheatsheet>")[0].strip()


def retrieve_synth(model, memory, item):
    pairs = memory.of("pair")
    sheet = memory.of("sheet")[0].text if memory.of("sheet") else ""
    if not pairs:
        return View(sheet)
    top = [pairs[i] for i in embed.top(item["context"], [r.when for r in pairs], TOP)]
    notes = "\n\n".join(f"Input: {r.when}\nOutput: {r.text}" for r in top)
    prompt = (SYNTH.replace("[[PREVIOUS_CHEATSHEET]]", sheet or "(empty)").replace("[[PREVIOUS_INPUT_OUTPUT_PAIRS]]", notes)
              .replace("[[NEXT_INPUT]]", item["context"]))
    new = cheatsheet(model.one("You are a careful curator of a cheatsheet.", prompt).text)
    return View(new if new is not None else sheet, [r.id for r in top])

# 4. обновление

CURATOR = (PROMPTS / "dc_curator.txt").read_text()


def reflect(ctx, ep, memory):
    prompt = (CURATOR.replace("[[PREVIOUS_CHEATSHEET]]", inject.plain(memory.records) or "(empty)")
              .replace("[[QUESTION]]", ep.question).replace("[[MODEL_ANSWER]]", ep.output))
    return cheatsheet(ctx.model.one("You are a careful curator of a cheatsheet.", prompt).text)


def curate(ctx, memory, sheets):
    for s in sheets:
        memory.rewrite("sheet", s)


def remember(ctx, ep, memory):
    return ep


def store(ctx, memory, episodes):
    for ep in episodes:
        memory.add(ep.output, kind="pair", when=ep.question)
        if ep.context:
            memory.rewrite("sheet", ep.context)


dc = Method("dc", MEMORY, inject.full(inject.plain), Feedback("none"), Update(reflect, curate))
dc_rs = Method("dc_rs", MEMORY_RS, retrieve_synth, Feedback("none"), Update(remember, store))
