"""Dynamic Cheatsheet: один вызов после каждой задачи переписывает всю память целиком, без метки.
Промпт куратора взят из апстрима как есть (prompts/dc_curator.txt)."""
from pathlib import Path

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
