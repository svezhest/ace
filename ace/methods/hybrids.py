"""Гибриды: деталь одного метода внутри другого, замена на одном уровне ace.

ace_bo2     извлечение: рефлектор ACE дважды и селектор выбирает один набор уроков (Best-of-N из SCOPE). Кандидаты
            при температуре 0.7, как у scope_bo2: при T = 0 два кандидата почти одинаковы.
ace_opt     память: пункты ACE с пределом SCOPE вместо отсева вредных — сверх 10 пунктов оптимизатор правил
            (конфликты, поглощение, слияние) сжимает до 8, остаток обрезается до 10 (memory/ace.py: CappedPlaybook)
ace_hooks   Hooks(ACE) с исполнением python: урок по ошибке инструмента дописывается в конец истории после
            шага с той же ошибкой (wrap/hooks.py)
ace_group   извлечение: контраст TF-GRPO по группе попыток (3 при T = 0.7, награды — верный ответ; в зачёт — попытка
            при T = 0, как у ace, в группу не входит) -> групповое преимущество, не больше 1 опыта; опыт уроком идёт
            куратору ACE. Меток нет, поэтому память без счётчиков и отсева, как ace_text."""
from ..env import Sandbox
from ..extract.ace import Reflector
from ..extract.best import BestOf, one_of_two
from ..extract.scope import BEST_OF_TEMPERATURE
from ..extract.tfgrpo import Contrast
from ..learner import swap
from ..loop import Attempts
from ..memory.ace import CappedPlaybook, Playbook
from ..wrap.hooks import Hooks
from .ace import ace

GROUP, GROUP_TEMPERATURE = 3, 0.7

ace_bo2 = swap(ace, "ace_bo2", extract=BestOf(Reflector(temperature=BEST_OF_TEMPERATURE), 2, one_of_two))
ace_opt = swap(ace, "ace_opt", memory=CappedPlaybook())
ace_hooks = Hooks(swap(ace, env=Sandbox()), "ace_hooks")
ace_group = swap(ace, "ace_group", extract=Contrast(library=False), memory=Playbook(prune=None),
                 attempts=Attempts(1 + GROUP, lambda k: 0 if k == 0 else GROUP_TEMPERATURE))
