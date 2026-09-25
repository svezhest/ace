"""Training-Free GRPO (youtu-agent: utu/practice/training_free_grpo.py, experience_updater.py). Параметры из
configs/practice/math_reasoning.yaml и configs/agents/practice/math_agent.yaml.

    попытки     в зачёт итоговый агент апстрима: T = 0.3, top_p 0.95; группа для обучения — G = 5 попыток при
                T = 0.7 (rollout_temperature), top_p тот же 0.95 (rollout меняет у агента только температуру,
                training_free_grpo.py:84)
    вердикт     верный ответ, награда 0/1
    извлечение  контраст на батче, стадиями по всему батчу (extract/tfgrpo.py): сводки -> групповые
                преимущества, не больше 1 опыта -> сверки с библиотекой -> операции
    память      библиотека опытов, план батча раз в 20 вопросов (memory/tfgrpo.py); неполный батч отбрасывается
    показ       вся библиотека (show/tfgrpo.py)
Батч в апстриме 50 из 100 задач, 2 шага за эпоху; у нас 20 из 40."""
from ..extract.tfgrpo import Contrast
from ..learner import Learner
from ..loop import Attempts, first
from ..memory.tfgrpo import Library
from ..show.tfgrpo import EXPERIENCES

GROUP, TEMPERATURE = 5, 0.7         # grpo_n, rollout_temperature
SCORED_TEMPERATURE, TOP_P = 0.3, 0.95   # итоговый агент апстрима (math_agent.yaml)
BATCH = 20

tfgrpo = Learner("tfgrpo", memory=Library(), show=EXPERIENCES, extract=Contrast(),
                 attempts=Attempts(1 + GROUP, lambda k: SCORED_TEMPERATURE if k == 0 else TEMPERATURE, lambda k: TOP_P,
                                   first), every=BATCH)
