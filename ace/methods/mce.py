"""MCE (meta-context-engineering: mce/main.py, utils.py, meta_agent.py, base_agent.py, prompts/).

mce = Meta(базовый агент с файлами):
    мета        итерация = проход; в начале итерации мета-агент с файлами пишет навык, в конце прохода val,
                следующая итерация — с лучшей по val из пройденных (wrap/mce.py)
    память      файлы context/, их правит базовый агент по навыку на батче (memory/mce.py)
    показ       все файлы context/ (интерфейса get_context, который апстрим пишет кодом, нет: MCE1)
    извлечение  нет: память читает сырое
    когда учится  батч 20; неполный батч применяется в конце прохода
Параметры scripts/train_symptom_diagnosis.sh: 3 итерации, train 50 батчами по 25, val 20; у нас 40 батчами
по 20 и val 10.

mce_ace = Meta(ACE): тот же мета-агент (промпт про рефлектор и куратор ACE), навык идёт в системные промпты
рефлектора и куратора ACE; в папках под-итераций только навык. Ученик — ace как есть."""
from .. import render
from ..extract import Raw
from ..learner import Learner, swap
from ..memory.mce import Context
from ..show import Whole
from ..wrap.mce import META, META_ACE, Meta, meta_agent
from .ace import ace

BATCH, ITERATIONS = 20, 3

base = Learner("mce_base", memory=Context(), show=Whole(line=render.plain, sep="\n\n"), extract=Raw(), every=BATCH,
               flush=True, epochs=ITERATIONS)
mce = Meta(base, meta_agent(META), "mce")
mce_ace = Meta(swap(ace, epochs=ITERATIONS), meta_agent(META_ACE), "mce_ace")
