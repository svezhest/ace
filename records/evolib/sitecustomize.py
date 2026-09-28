# Окружение прогона апстрима, код апстрима не меняется.
# Адрес: апстрим знает только AzureOpenAI с токеном Azure AD; клиент — OpenAI на тот же --endpoint, ключ-заглушка.
# Рандом: сида у апстрима нет, глобальный random — от 0.
import random

import openai

openai.AzureOpenAI = lambda azure_endpoint, **_: openai.OpenAI(base_url=azure_endpoint, api_key="x")
random.seed(0)
