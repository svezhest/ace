"""Гибриды: деталь одного метода внутри другого, замена на одном уровне ace_stand.

ace_stand_bo2     извлечение: рефлектор ACE дважды и селектор выбирает один набор уроков (Best-of-N из SCOPE).
                  Кандидаты при температуре 0.7, как у scope_bo2: при T = 0 два кандидата почти одинаковы.
ace_stand_opt     память: пункты ACE с пределом SCOPE вместо отсева вредных — сверх 10 пунктов оптимизатор правил
                  (конфликты, поглощение, слияние) сжимает до 8, остаток обрезается до 10 (memory/ace.py: CappedPlaybook)
ace_stand_hooks   Hooks(ACE) с исполнением python: урок по ошибке инструмента дописывается в конец истории после
                  шага с той же ошибкой (wrap/hooks.py)
ace_stand_group   извлечение: контраст TF-GRPO по группе попыток (3 при T = 0.7, награды — верный ответ; в зачёт —
                  попытка при T = 0, как у ace_stand, в группу не входит) -> групповое преимущество, не больше 1 опыта;
                  опыт уроком идёт куратору ACE. Меток нет, поэтому память без счётчиков и отсева, как ace_stand_text."""
from ..env import Sandbox
from ..extract.ace import Reflector
from ..extract.best import BestOf, one_of_two
from ..extract.scope import BEST_OF_TEMPERATURE
from ..extract.tfgrpo import Contrast
from ..learner import swap
from ..loop import Attempts
from ..memory.ace import CappedPlaybook, Playbook
from ..wrap.hooks import Hooks
from .ace import ace_stand

GROUP, GROUP_TEMPERATURE = 3, 0.7

ace_stand_bo2 = swap(ace_stand, "ace_stand_bo2", extract=BestOf(Reflector(temperature=BEST_OF_TEMPERATURE), 2, one_of_two))
ace_stand_opt = swap(ace_stand, "ace_stand_opt", memory=CappedPlaybook())
ace_stand_hooks = Hooks(swap(ace_stand, env=Sandbox()), "ace_stand_hooks")
ace_stand_group = swap(ace_stand, "ace_stand_group", extract=Contrast(library=False, scored=True),
                       memory=Playbook(prune=None), attempts=Attempts(1 + GROUP, lambda k: 0 if k == 0 else GROUP_TEMPERATURE))
