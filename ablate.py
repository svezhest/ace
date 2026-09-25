"""Цепочка абляций по уровням: каждая ступень — одна замена уровня относительно предыдущей ступени или базы
своего блока (она указана в комментарии). Шесть методов — отдельными строками для сравнения.
python ablate.py TASK [N] [STEP ...]; EPOCHS и OFFLINE — как у run.py (ace/config.py)."""
import sys

from ace import config, prompts, verdict
from ace.env import Sandbox
from ace.hooks import Hooks
from ace.learner import swap
from ace.loop import Attempts, run, vote
from ace.methods import METHODS
from ace.methods.evolib import ATTEMPTS
from ace.methods.mce import ITERATIONS
from ace.model import Model
from ace.show import Catalog, Whole
from ace.tasks import TASKS

SPREAD = 0.7                # температура попыток после первой (self-consistency, как в старом sc3)


def spread(k):
    return 0 if k == 0 else SPREAD


def later(name):
    """Ступень, метода которой ещё нет в реестре, пропускается."""
    return {name: METHODS[name]} if name in METHODS else {}


m = METHODS
ace, baseline, evolib, scope_code = m["ace"], m["baseline"], m["evolib"], m["scope_code"]
ace_code = swap(ace, "ace_code", env=Sandbox())

CHAIN = {
    # контроли
    "baseline": baseline,
    "placebo": swap(baseline, "placebo", show=Whole(empty=prompts.text("placebo"))),   # показ: та же длина без знаний
    "sc3": swap(baseline, "sc3", attempts=Attempts(3, spread, pick=vote)),    # попытки: столько же вызовов, что у ace, без памяти

    # шесть методов, как в апстримах
    "ace_exact": m["ace_exact"],
    "dc": m["dc"],
    "scope": m["scope"],
    "tfgrpo": m["tfgrpo"],
    "evolib": evolib,
    "mce": m["mce"],

    # база цепочки — ace стенда: рефлектор с метками, куратор операциями, отсев вредных, показ всего
    "ace": ace,
    # извлечение (от ace)
    "ace_text": m["ace_text"],      # рефлексия свободным текстом; без меток и память без отсева — иначе стык не сойдётся
    "ace_bo2": m["ace_bo2"],        # Best-of-2: рефлектор дважды при T=0.7, селектор выбирает набор уроков
    **later("ace_group"),           # контраст TF-GRPO по группе попыток (вердикт группы + извлечение)
    # память (от ace)
    "ace_opt": m["ace_opt"],        # предел 10 с оптимизатором SCOPE вместо отсева
    "ace_rewrite": m["ace_rewrite"],    # куратор переписывает всю память
    # показ (от ace)
    "ace_catalog": swap(ace, "ace_catalog", show=Catalog()),   # каталог id и первых строк, тела — read
    "ace_code": ace_code,           # среда: исполнение python (база хуков)
    "ace_hooks": Hooks(ace_code, "ace_hooks"),                 # от ace_code: урок после ошибки в конец истории
    "ace_hooks_system": Hooks(ace_code, "ace_hooks_system", show="system"),   # от ace_code: хуки в системном промпте с начала
    # мета (от ace)
    "ace_e3": swap(ace, "ace_e3", epochs=ITERATIONS),          # протокол: 3 прохода, как у меты
    "mce_ace": m["mce_ace"],        # от ace_e3: MCE над ACE — навык рефлектору и куратору, откат к лучшей по val

    # вердикт (на EvoLib; evolib — голосование группы)
    "evolib_judge": m["evolib_judge"],  # судья: баллы по вердикту попытки
    "evolib_golden": swap(m["evolib_judge"], "evolib_golden", verdict=verdict.golden),   # от evolib_judge: верный ответ
    # попытки (от evolib)
    "evolib_n5": swap(evolib, "evolib_n5", attempts=Attempts(5, pick=vote)),                  # число: 5 вместо 3
    "evolib_t07": swap(evolib, "evolib_t07", attempts=Attempts(ATTEMPTS, spread, pick=vote)),  # различие: ещё и температура

    # показ посреди попытки (SCOPE; правило на шаге бывает только у решателя с инструментами)
    "scope_code": scope_code,       # от scope: исполнение python
    "scope_append": swap(scope_code, "scope_append", patch="append"),  # от scope_code: правило в конец истории вместо перезаписи системного промпта
}

if __name__ == "__main__":
    task = TASKS[sys.argv[1]]
    n = int(sys.argv[2]) if len(sys.argv) > 2 else config.SIZE
    for name in sys.argv[3:] or CHAIN:
        print(run(task, CHAIN[name], Model(), n, f"{config.RESULTS}/{task.name}{n}/{name}",
                  epochs=config.EPOCHS, offline=config.OFFLINE))
