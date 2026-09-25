"""Цепочка абляций по уровням: каждая ступень — одна замена уровня относительно предыдущей ступени или базы
своего блока (она указана в комментарии). Шесть методов — отдельными строками для сравнения.
python ablate.py TASK [N] [STEP ...]; каждая ступень идёт по своему протоколу (learner.protocol)."""
import sys

from ace import config, prompts, verdict
from ace.env import Sandbox
from ace.learner import swap
from ace.loop import Attempts, Protocol, run, vote
from ace.methods import METHODS
from ace.methods.mce import ITERATIONS
from ace.model import Model
from ace.show import Catalog, Whole
from ace.show.evolib import Sampler
from ace.show.scope import StrategicRules
from ace.tasks import TASKS
from ace.wrap.hooks import Hooks

SPREAD = 0.7                # температура попыток после первой (self-consistency)


def spread(k):
    return 0 if k == 0 else SPREAD


def later(name):
    """Ступень, метода которой ещё нет в реестре, пропускается."""
    return {name: METHODS[name]} if name in METHODS else {}


m = METHODS
ace_stand, baseline, evolib, scope_code = m["ace_stand"], m["baseline"], m["evolib"], m["scope_code"]
ace_stand_code = swap(ace_stand, "ace_stand_code", env=Sandbox())

CHAIN = {
    # контроли
    "baseline": baseline,
    "placebo": swap(baseline, "placebo", show=Whole(empty=prompts.text("placebo"))),   # показ: та же длина без знаний
    "sc3": swap(baseline, "sc3", attempts=Attempts(3, spread, pick=vote)),    # попытки: столько же вызовов, что у ace_stand, без памяти

    # шесть методов, как в апстримах
    "ace": m["ace"],
    "dc": m["dc"],
    "scope": m["scope"],
    "tfgrpo": m["tfgrpo"],
    "evolib": evolib,
    "mce": m["mce"],

    # база цепочки — ace_stand: рефлектор с метками, куратор операциями, отсев вредных, показ всего
    "ace_stand": ace_stand,
    # извлечение (от ace_stand)
    "ace_stand_text": m["ace_stand_text"],      # рефлексия свободным текстом; без меток и память без отсева — иначе стык не сойдётся
    "ace_stand_bo2": m["ace_stand_bo2"],        # Best-of-2: рефлектор дважды при T=0.7, селектор выбирает набор уроков
    **later("ace_stand_group"),           # контраст TF-GRPO по группе попыток (вердикт группы + извлечение)
    # память (от ace_stand)
    "ace_stand_opt": m["ace_stand_opt"],        # предел 10 с оптимизатором SCOPE вместо отсева
    "ace_stand_rewrite": m["ace_stand_rewrite"],    # куратор переписывает всю память
    # показ (от ace_stand)
    "ace_stand_catalog": swap(ace_stand, "ace_stand_catalog", show=Catalog()),   # каталог id и первых строк, тела — read
    "ace_stand_code": ace_stand_code,           # среда: исполнение python (база хуков)
    "ace_stand_hooks": Hooks(ace_stand_code, "ace_stand_hooks"),                 # от ace_stand_code: урок после ошибки в конец истории
    "ace_stand_hooks_system": Hooks(ace_stand_code, "ace_stand_hooks_system", show="system"),   # от ace_stand_code: хуки в системном промпте с начала
    # мета (от ace_stand)
    "ace_stand_e3": swap(ace_stand, "ace_stand_e3", protocol=Protocol(offline=True, epochs=ITERATIONS)),   # протокол меты: офлайн, 3 прохода
    "mce_ace_stand": m["mce_ace_stand"],        # от ace_stand_e3: MCE над ACE — навык рефлектору и куратору, откат к лучшей по val

    # вердикт (на EvoLib; evolib — голосование группы)
    "evolib_judge": m["evolib_judge"],  # судья: баллы по вердикту попытки
    "evolib_golden": swap(m["evolib_judge"], "evolib_golden", verdict=verdict.golden),   # от evolib_judge: верный ответ
    # попытки (от evolib)
    "evolib_n5": swap(evolib, "evolib_n5", attempts=Attempts(5, pick=vote)),                  # число: 5 вместо 3
    "evolib_t07": swap(evolib, "evolib_t07", show=Sampler(temperature=spread)),                # различие: ещё и температура

    # показ посреди попытки (SCOPE; правило на шаге бывает только у решателя с инструментами)
    "scope_code": scope_code,       # от scope: исполнение python
    "scope_append": swap(scope_code, "scope_append", show=StrategicRules("append")),  # от scope_code: правило в конец истории вместо перезаписи системного промпта
}

if __name__ == "__main__":
    task = TASKS[sys.argv[1]]
    n = int(sys.argv[2]) if len(sys.argv) > 2 else config.SIZE
    for name in sys.argv[3:] or CHAIN:
        print(run(task, CHAIN[name], Model(), n, f"{config.RESULTS}/{task.name}{n}/{name}"))
