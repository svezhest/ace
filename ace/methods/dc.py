"""Dynamic Cheatsheet: один вызов после каждой задачи переписывает всю память целиком, без метки.
Промпт куратора взят из апстрима как есть (prompts/dc_curator.txt)."""
from pathlib import Path

from .. import embed
from ..loop import Method

CURATOR = (Path(__file__).parent / "prompts" / "dc_curator.txt").read_text()


def reflect(model, trace, memory):
    prompt = (CURATOR.replace("[[PREVIOUS_CHEATSHEET]]", memory.text() or "(empty)")
              .replace("[[QUESTION]]", trace.question).replace("[[MODEL_ANSWER]]", trace.output))
    return model.one("You are a careful curator of a cheatsheet.", prompt).text


def curate(model, memory, new_text):
    # апстрим оставляет старый cheatsheet, если блок не найден
    if "<cheatsheet>" in new_text:
        new_text = new_text.split("<cheatsheet>", 1)[1].split("</cheatsheet>")[0]
        memory.replace_all(new_text.strip())


dc = Method("dc", reflect=reflect, curate=curate, signal="none")


# DC-RS: до решения достаём top-3 прошлых пар (вопрос, ответ) и синтезируем из них cheatsheet.
# Косинус по BGE-M3 (в статье text-embedding-3-small).
SYNTH = (Path(__file__).parent / "prompts" / "dc_synth.txt").read_text()
TOP = 3


def prepare(model, memory, item):
    pairs = [r for r in memory.records if r.kind == "episode"]
    if not pairs:
        return
    top = [pairs[i] for i in embed.top(item["context"], [r.when for r in pairs], TOP)]
    notes = "\n\n".join(f"Input: {r.when}\nOutput: {r.text}" for r in top)
    sheet = next((r.text for r in memory.records if r.kind == "sheet"), "(empty)")
    prompt = (SYNTH.replace("[[PREVIOUS_CHEATSHEET]]", sheet).replace("[[PREVIOUS_INPUT_OUTPUT_PAIRS]]", notes)
              .replace("[[NEXT_INPUT]]", item["context"]))
    new = model.one("You are a careful curator of a cheatsheet.", prompt).text
    if "<cheatsheet>" in new:
        memory.records = [r for r in memory.records if r.kind != "sheet"]
        memory.add(new.split("<cheatsheet>", 1)[1].split("</cheatsheet>")[0].strip(), kind="sheet")


def remember(model, trace, memory):
    memory.add(trace.output, kind="episode", when=trace.question)
    return None


def inject_rs(memory):
    return next((r.text for r in memory.records if r.kind == "sheet"), "")


dc_rs = Method("dc_rs", prepare=prepare, inject=inject_rs, reflect=remember, signal="none")
