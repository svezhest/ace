"""EvoLib (EvoLib/EvoLib/evolib_agent.py, вариант HMMT из eval_main.py: без синтетических тестов).

    попытки     3; различаются выборкой памяти (одно случайное число на попытку выбирает ветку показа)
    в зачёт     ответ большинства
    вердикт     попытки — нет; группы — голосование (попытка «верна», если её ответ совпал с ответом большинства)
    извлечение  баллы, IG, insight, лучшее решение попытки (extract/evolib.py)
    память      библиотека skills и insights с Future IG и IG при рождении, слиянием похожих и скрытым лучшим
                решением вопроса; улучшает ли новое решение, решает память, при споре — сравнение решений моделью
                (memory/evolib.py)
    решатель    апстрима: выборка по весу из ветки skills или insights в промпте HMMT_SOLVER_PROMPT,
                решение подзадачами (solver/evolib.py)
Параметры вызовов у hmmt — как у апстрима на его модели (reasoning API), у задач стенда — стенда.
evolib_judge — вариант стенда: баллы от судьи (вердикт попытки judge), insight только при неудаче лучшей и с её
    вердиктом в промпте («Evaluation: wrong», как Test Result кодовых задач апстрима), без деления баллов и без
    сравнения решений.
Эпох в апстриме тысячи (5000 итераций по кругу), у нас это параметр протокола EPOCHS."""
from .. import verdict
from ..extract.evolib import Gains
from ..learner import Learner, swap
from ..loop import Attempts, vote
from ..memory.evolib import Library
from ..solver.evolib import SAMPLER

ATTEMPTS = 3                # k_q_per_problem

evolib = Learner("evolib", memory=Library(), solver=SAMPLER, extract=Gains(), attempts=Attempts(ATTEMPTS, pick=vote),
                 verdict=verdict.none, group_verdict=verdict.vote)
evolib_judge = swap(evolib, "evolib_judge", extract=Gains(evaluated=True), verdict=verdict.judge, group_verdict=verdict.none)
