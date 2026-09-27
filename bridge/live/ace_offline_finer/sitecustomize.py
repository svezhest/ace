# адрес модели для апстрима ACE: utils.py:30 зашивает api.openai.com, подменяем base_url из ACE_BASE_URL
import os
import openai

_Base = openai.OpenAI


class _Local(_Base):
    def __init__(self, *a, **k):
        k["base_url"] = os.environ["ACE_BASE_URL"]
        super().__init__(*a, **k)


openai.OpenAI = _Local
