"""SCOPE апстрима (strategic_store.py, examples/basic_usage.py): память в системном промпте решателя — strategic
правила (get_strategic_rules_text) и «## Learned Guideline:» на tactical правило."""
from .. import prompts, render

INTRO = prompts.text("scope_strategic_intro")
GUIDELINE = prompts.text("scope_guideline")


def strategic_text(book):
    """get_strategic_rules_text апстрима; пусто без правил."""
    return render.strategic(INTRO, render.domains(book.domains.items()) if book.records() else "")


def guidelines(records):
    """Правила в конце системного промпта: «## Learned Guideline:» на каждое."""
    return render.lines(records, render.prefixed(GUIDELINE), "\n\n")


def current_system(system, book):
    """Системный промпт решателя сейчас: как при запуске попытки и tactical правила, принятые в ней."""
    return system + "\n\n" + guidelines(book.tactical) if book.tactical else system
