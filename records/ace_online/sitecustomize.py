# окружение прогона апстрима ACE, код апстрима не меняется
# адрес: utils.py:30 зашивает api.openai.com, подменяем base_url из ACE_BASE_URL
# рандом: сида у апстрима нет (random — джиттер паузы перед повтором в llm.py), глобальный random — от 0
import os
import random

import openai

_Base = openai.OpenAI


class _Local(_Base):
    def __init__(self, *a, **k):
        k["base_url"] = os.environ["ACE_BASE_URL"]
        super().__init__(*a, **k)


openai.OpenAI = _Local
random.seed(0)
