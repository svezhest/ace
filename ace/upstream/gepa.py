"""GEPA апстрима (gepa-ai/gepa: api.py, adapters/default_adapter/default_adapter.py, README «Quick Start»): текст
кандидата — общий для решателя (системный промпт) и рефлексии (что переписывать)."""
from .. import prompts
from ..tasks import variant

SEED_AIME = prompts.text("gepa_seed_aime")


def seed(task):
    """seed_candidate: у aime — seed_prompt квикстарта, у задач стенда — роль и инструкция задачи (S2)."""
    if variant("gepa", task) == "aime":
        return SEED_AIME
    return f"{task.system} {task.instr}"


def current(memory, task):
    """Текст кандидата: выученный (и пустой, если рефлексия дала пустой) или seed задачи, пока рефлексии не было."""
    return seed(task) if memory.text is None else memory.text
