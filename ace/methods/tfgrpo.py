"""Training-Free GRPO (youtu-agent: utu/practice/training_free_grpo.py, experience_updater.py). Параметры из
configs/practice/math_reasoning.yaml и configs/agents/practice/math_agent.yaml.

    протокол    как у апстрима: проход по train — только обучение (rollout), в зачёт — тест итоговым агентом
                с библиотекой после обучения (final)
    попытки     группа из G = 5 попыток агента апстрима при T = 0.7 (rollout_temperature), top_p 0.95; на тесте
                одна попытка итогового агента; температуру и top_p ставит агент (solver/tfgrpo.py)
    вердикт     верный ответ, награда 0/1
    извлечение  контраст на батче, стадиями по всему батчу (extract/tfgrpo.py): сводки -> групповые
                преимущества, не больше 1 опыта -> сверки с библиотекой -> операции
    память      библиотека опытов, план батча раз в 20 вопросов (memory/tfgrpo.py); неполный батч отбрасывается
    решатель    агент апстрима: опыты в задаче rollout и в инструкциях итогового агента (solver/tfgrpo.py)
Батч в апстриме 50 из 100 вопросов, 2 шага за эпоху; у нас 20 из 40."""
from ..extract.tfgrpo import Contrast
from ..learner import Learner
from ..loop import Attempts, Protocol, first
from ..memory.tfgrpo import Experiences
from ..solver.tfgrpo import AGENT

GROUP = 5                   # grpo_n
BATCH = 20

tfgrpo = Learner("tfgrpo", memory=Experiences(), solver=AGENT, extract=Contrast(),
                 attempts=Attempts(GROUP, pick=first), every=BATCH,
                 protocol=Protocol(offline=True, final=True))
