"""Цепочка абляций по уровням: каждая ступень — одна замена уровня относительно предыдущей ступени или базы
своего блока (она указана в комментарии). Семь методов — отдельными строками для сравнения.
python ablate.py TASK [N] [STEP ...]; каждая ступень идёт по своему протоколу (learner.protocol)."""
import sys
from dataclasses import replace

from ace import prompts, verdict
from ace.env import Sandbox
from ace.learner import swap
from ace.loop import Attempts, Protocol, folder, run, spread, vote
from ace.methods import METHODS
from ace.methods.mce import ITERATIONS
from ace.model import Model
from ace.show import Catalog, Whole
from ace.show.scope import StrategicRules
from ace.solver.evolib import Sampler
from ace.tasks import TASKS
from ace.wrap import Gate
from ace.wrap.hooks import Hooks

ace_stand = METHODS["ace_stand"]
baseline = METHODS["baseline"]
evolib = METHODS["evolib"]
scope_code = METHODS["scope_code"]
ace_stand_code = swap(ace_stand, "ace_stand_code", env=Sandbox())


def untrained(method):
    """Тот же метод без обучения: свой решатель, показ и попытки, пустая память; протокол без проходов (epochs = 0) —
    сразу тест. Контроль для метода со своим решателем: разница с ним — от памяти, а не от решателя."""
    return swap(method, f"{method.name}_e0", protocol=replace(method.protocol, epochs=0))


CHAIN = {
    # контроли
    "baseline": baseline,
    # показ: та же длина без знаний
    "placebo": swap(baseline, "placebo", show=Whole(empty=prompts.text("placebo"))),
    # попытки: столько же вызовов, что у ace_stand, без памяти
    "sc3": swap(baseline, "sc3", attempts=Attempts(3, spread, pick=vote)),

    # семь методов, как в апстримах
    "ace": METHODS["ace"],
    "dc": METHODS["dc"],
    "scope": METHODS["scope"],
    "tfgrpo": METHODS["tfgrpo"],
    "evolib": evolib,
    "mce": METHODS["mce"],
    "gepa": METHODS["gepa"],
    # протокол: те же методы со своим решателем без обучения
    "ace_e0": untrained(METHODS["ace"]),
    "dc_e0": untrained(METHODS["dc"]),
    "tfgrpo_e0": untrained(METHODS["tfgrpo"]),
    "evolib_e0": untrained(evolib),
    "mce_e0": untrained(METHODS["mce"]),
    "gepa_e0": untrained(METHODS["gepa"]),

    # база цепочки — ace_stand: рефлектор с метками, куратор операциями, отсев вредных, показ всего
    "ace_stand": ace_stand,
    # извлечение (от ace_stand)
    # рефлексия свободным текстом; без меток и память без отсева — иначе стык не сойдётся
    "ace_stand_text": METHODS["ace_stand_text"],
    # Best-of-2: рефлектор дважды при T=0.7, селектор выбирает набор уроков
    "ace_stand_bo2": METHODS["ace_stand_bo2"],
    # контраст TF-GRPO по группе попыток (вердикт группы + извлечение)
    "ace_stand_group": METHODS["ace_stand_group"],
    # память (от ace_stand)
    # предел 10 с оптимизатором SCOPE вместо отсева
    "ace_stand_opt": METHODS["ace_stand_opt"],
    # куратор переписывает всю память
    "ace_stand_rewrite": METHODS["ace_stand_rewrite"],
    # показ (от ace_stand)
    # каталог id и первых строк, тела — read
    "ace_stand_catalog": swap(ace_stand, "ace_stand_catalog", show=Catalog()),
    # среда: исполнение python (база хуков)
    "ace_stand_code": ace_stand_code,
    # от ace_stand_code: контейнер живёт попытку (файлы между вызовами)
    "ace_stand_code_attempt": swap(ace_stand_code, "ace_stand_code_attempt", env=Sandbox(per="attempt")),
    # от ace_stand_code: урок после ошибки исполнения в конец истории
    "ace_stand_hooks": METHODS["ace_stand_hooks"],
    # от ace_stand_hooks: хуки в системном промпте с начала
    "ace_stand_hooks_system": Hooks(ace_stand_code, "ace_stand_hooks_system", show="system"),
    # от ace_stand_hooks: урок без модели — ошибка и следующий прошедший вызов
    "ace_stand_hooks_raw": Hooks(ace_stand_code, "ace_stand_hooks_raw", learn="raw"),
    # мета (от ace_stand)
    # правка батча остаётся, только если на val не хуже
    "ace_stand_gate": Gate(ace_stand, "ace_stand_gate"),
    # протокол меты: офлайн, 3 прохода
    "ace_stand_e3": swap(ace_stand, "ace_stand_e3", protocol=Protocol(offline=True, epochs=ITERATIONS)),
    # от ace_stand_e3: MCE над ACE — навык рефлектору и куратору, откат к лучшей по val
    "mce_ace_stand": METHODS["mce_ace_stand"],

    # вердикт (на EvoLib; evolib — голосование группы)
    # судья: баллы по вердикту попытки
    "evolib_judge": METHODS["evolib_judge"],
    # от evolib_judge: верный ответ
    "evolib_golden": swap(METHODS["evolib_judge"], "evolib_golden", verdict=verdict.golden),
    # попытки (от evolib)
    # число: 5 вместо 3
    "evolib_n5": swap(evolib, "evolib_n5", attempts=Attempts(5, pick=vote)),
    # различие: ещё и температура (параметр решателя)
    "evolib_t07": swap(evolib, "evolib_t07", solver=Sampler(temperature=spread)),

    # показ посреди попытки (SCOPE; правило на шаге бывает только у решателя с инструментами)
    # от scope: исполнение python
    "scope_code": scope_code,
    # от scope_code: правило в конец истории вместо перезаписи системного промпта
    "scope_append": swap(scope_code, "scope_append", show=StrategicRules("append")),
}

if __name__ == "__main__":
    task = TASKS[sys.argv[1]]
    n = int(sys.argv[2]) if len(sys.argv) > 2 else task.size()
    for name in sys.argv[3:] or CHAIN:
        model = Model()
        try:
            print(run(task, CHAIN[name], model, n, folder(task, n, CHAIN[name], model)))
        except Exception as error:          # ступень не собралась или не запустилась — цепочка идёт дальше
            print(f"{name}: {error!r}", flush=True)
