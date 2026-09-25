"""Гибриды: деталь одного метода внутри другого, замена на одном уровне ace.

ace_bo2     извлечение: рефлектор ACE дважды и селектор выбирает один набор уроков (Best-of-N из SCOPE). Оба
            кандидата при температуре 0, как в старом коде.
ace_opt     память: пункты ACE с пределом SCOPE вместо отсева вредных — сверх 10 пунктов оптимизатор правил
            (конфликты, поглощение, слияние) сжимает до 8, остаток обрезается до 10; нетронутые пункты остаются
            со своими счётчиками, исправленные и слитые — новые пункты с нуля
ace_hooks   Hooks(ACE) с исполнением python: урок по ошибке инструмента дописывается в конец истории после
            шага с той же ошибкой (ace/hooks.py)
ace_group (контраст TF-GRPO по группе попыток) — после переноса TF-GRPO."""
from .. import prompts, render
from ..env import Sandbox
from ..extract.ace import Reflector
from ..extract.best import BestOf
from ..hooks import Hooks
from ..learner import swap
from .ace import Playbook, ace
from .scope import CAP, TARGET, compress, rule_optimizer

SELECT = prompts.load("hybrid_select")
SELECTOR = prompts.text("selector_system")


def one_of_two(ex, group, candidates):
    """Модель выбирает набор уроков: ответ «1» или «2»; без ответа первый."""
    a, b = (render.lessons(x.lessons) for x in candidates[:2])
    out = ex.model.run(SELECTOR, SELECT.fill(a=a, b=b)).output
    return 1 if (out or "1").strip().startswith("2") else 0


class CappedPlaybook(Playbook):
    def __init__(self, cap=CAP, target=TARGET):
        super().__init__(prune=None)
        self.cap, self.target, self.optimizer = cap, target, rule_optimizer()

    def learn(self, ex, extractions):
        super().learn(ex, extractions)
        self.items = compress(ex.model, self.items, self.optimizer, self.target, self.cap,
                              lambda x: self.record(self.ids.next(), x["rule"]))


ace_bo2 = swap(ace, "ace_bo2", extract=BestOf(Reflector(), 2, one_of_two))
ace_opt = swap(ace, "ace_opt", memory=CappedPlaybook())
ace_hooks = Hooks(swap(ace, env=Sandbox()), "ace_hooks")
