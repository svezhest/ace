"""MCE (meta-context-engineering: mce/main.py, utils.py, meta_agent.py, base_agent.py, eval.py, prompts/).

mce = Iterations(базовый агент апстрима) — метод апстрима целиком, агенты — Claude Agent SDK на модели стенда
(model/claude.py: CLI через LiteLLM proxy):
    мета        итерация = проход; в начале — случайная выборка train и мета-агент (Claude SDK, cwd — workspace)
                пишет .claude/skills/learning-context/SKILL.md; в конце прохода val, итерация — в evaluations.json,
                следующая — от лучшей по val (wrap/mce.py: Iterations)
    память      папка под-итерации на диске: context/, interfaces/ (у symptom — get_context), навык; на батче —
                data/train.json и базовый агент Claude SDK с проверкой интерфейсов (memory/mce.py: Folder)
    решатель    среда задачи: у symptom — get_context и промпт диагноза апстрима, у задач стенда — общий
                решатель со всеми файлами (solver/mce.py)
    извлечение  нет: память читает сырое
    когда учится  батч 20; неполный батч применяется в конце прохода
    протокол    офлайн: 3 итерации по train, val после каждой, тест памятью лучшей по val итерации
Параметры scripts/train_symptom_diagnosis.sh: 3 итерации, train 50 батчами по 25, val 20; у нас 40 батчами
по 20 и val 10.

mce_fs = Meta(базовый агент стенда) — наш вариант: мета-агент и базовый агент — модель стенда с файловыми
инструментами fs.py в памяти (без SDK и диска), папка навыка .agent/ (DEVIATIONS MCE3, MCE5), без интерфейсов.

mce_ace_stand = Meta(ACE): тот же мета-агент mce_fs (промпт про рефлектор и куратор ACE), навык идёт в системные промпты
рефлектора и куратора ACE; в папках под-итераций только навык. Ученик — ace_stand как есть."""
from .. import render
from ..extract import Raw
from ..learner import Learner, swap
from ..loop import Protocol
from ..memory.mce import Context, Folder
from ..show import Whole
from ..solver.mce import Environment
from ..wrap.mce import META, META_ACE, Iterations, Meta, MetaAgent
from .ace import ace_stand

BATCH, ITERATIONS = 20, 3

PROTOCOL = Protocol(offline=True, epochs=ITERATIONS)     # итерация = проход по train, val после неё

mce = Iterations(Learner("mce", memory=Folder(), solver=Environment(), extract=Raw(), every=BATCH, flush=True,
                         protocol=PROTOCOL))
base = Learner("mce_base", memory=Context(), show=Whole(line=render.plain, sep="\n\n"), extract=Raw(), every=BATCH,
               flush=True, protocol=PROTOCOL)
mce_fs = Meta(base, MetaAgent(META), "mce_fs")
mce_ace_stand = Meta(swap(ace_stand, protocol=PROTOCOL), MetaAgent(META_ACE), "mce_ace_stand")
