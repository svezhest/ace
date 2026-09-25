"""Показ SCOPE (SCOPE/scope: strategic_store.py, examples/basic_usage.py).

При запуске попытки — strategic правила перспективы попытки текстом get_strategic_rules_text сразу за
системным промптом. После шага, где принято новое правило: patch="system" — системный промпт переписывается:
исходный + «## Learned Guideline:» на каждое tactical правило попытки (как в апстриме); patch="append" —
абляция: новые правила сообщением в конец истории, системный промпт и префикс истории целы."""
from ..loop import Prompt
from ..model import Patch
from ..upstream.scope import current_system, guidelines, strategic_text
from . import Show

class StrategicRules(Show):
    watches_steps = True
    reads = ("book",)

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
