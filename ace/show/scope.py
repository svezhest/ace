"""Показ SCOPE (SCOPE/scope: strategic_store.py, examples/basic_usage.py).

При запуске попытки — strategic правила перспективы попытки текстом get_strategic_rules_text сразу за
системным промптом. После шага, где принято новое правило: patch="system" — системный промпт переписывается:
исходный + «## Learned Guideline:» на каждое tactical правило попытки (как в апстриме); patch="append" —
абляция: новые правила сообщением в конец истории, системный промпт и префикс истории целы."""
from .. import prompts, render
from ..loop import Prompt
from ..model import Patch
from . import Show

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


class StrategicRules(Show):
    watches_steps = True

    def __init__(self, patch="system"):
        self.patch = patch

    def prompt(self, ex, memory, item, k):
        book = memory.book(k)
        text = strategic_text(book)
        return Prompt(text, shown=[r.id for r in book.records()]) if text else Prompt()

    def on_step(self, ex, memory, attempt, step):
        book = memory.book(attempt.k)
        new = [r for r in book.tactical if r.id not in attempt.shown]
        if not new:
            return None
        attempt.shown += [r.id for r in new]
        if self.patch == "append":
            return Patch(append=guidelines(new))
        return Patch(system=current_system(attempt.system, book))
