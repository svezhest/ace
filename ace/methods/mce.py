"""MCE (meta-context-engineering: mce/main.py, utils.py, meta_agent.py, base_agent.py, eval.py, prompts/).

mce = Iterations(базовый агент апстрима) — метод апстрима целиком, агенты — Claude Agent SDK на модели стенда
(model/claude.py: CLI через LiteLLM proxy):
    мета        итерация = проход; в начале — случайная выборка train и мета-агент (Claude SDK, cwd — workspace)
                пишет .claude/skills/learning-context/SKILL.md; в конце прохода val, итерация — в evaluations.json,
                следующая — от лучшей по val (wrap/mce.py: Iterations)
    память      папка под-итерации на диске: context/, interfaces/ (у symptom — get_context), навык; на батче —
                data/train.json и базовый агент Claude SDK с проверкой интерфейсов (memory/mce.py: Folder)
    показ       среда задачи: у symptom — get_context и промпт диагноза апстрима, у задач стенда — все файлы
                (show/mce.py)
    извлечение  нет: память читает сырое
    когда учится  батч 20; неполный батч применяется в конце прохода
Параметры scripts/train_symptom_diagnosis.sh: 3 итерации, train 50 батчами по 25, val 20; у нас 40 батчами
по 20 и val 10.

mce_fs = Meta(базовый агент стенда) — наш вариант: мета-агент и базовый агент — модель стенда с файловыми
инструментами fs.py в памяти (без SDK и диска), папка навыка .agent/ (DEVIATIONS MCE3, MCE5), без интерфейсов.

mce_ace_stand = Meta(ACE): тот же мета-агент mce_fs (промпт про рефлектор и куратор ACE), навык идёт в системные промпты
рефлектора и куратора ACE; в папках под-итераций только навык. Ученик — ace_stand как есть."""
from .. import render
from ..extract import Raw
from ..learner import Learner, swap
from ..memory.mce import Context, Folder
from ..show import Whole
from ..show.mce import Environment
from ..wrap.mce import META, META_ACE, Iterations, Meta, meta_agent
from .ace import ace_stand

BATCH, ITERATIONS = 20, 3

mce = Iterations(Learner("mce", memory=Folder(), show=Environment(), extract=Raw(), every=BATCH, flush=True,
                         epochs=ITERATIONS))
base = Learner("mce_base", memory=Context(), show=Whole(line=render.plain, sep="\n\n"), extract=Raw(), every=BATCH,
               flush=True, epochs=ITERATIONS)
mce_fs = Meta(base, meta_agent(META), "mce_fs")
mce_ace_stand = Meta(swap(ace_stand, epochs=ITERATIONS), meta_agent(META_ACE), "mce_ace_stand")
