# Окружение прогона апстрима, код апстрима не меняется.
# Адрес: апстрим знает только AzureOpenAI с токеном Azure AD; клиент — OpenAI на тот же --endpoint, ключ-заглушка.
# Рандом: сида у апстрима нет, глобальный random — от 0.
# Переходник (F): EvoLib зовёт extract_and_grade(решение, ответ), у matharena (e927660 и любой другой версии) —
# extract_and_grade(сообщения, число токенов, ответ, конфиг соревнования). Решение — одно сообщение assistant, число
# токенов 0 (идёт только в предупреждение), конфиг — hmmt_feb_2025.yaml: первые N задач берутся из hmmt_feb_2025.
import random

import openai
import yaml
from matharena import grader

openai.AzureOpenAI = lambda azure_endpoint, **_: openai.OpenAI(base_url=azure_endpoint, api_key="x")
random.seed(0)

CONFIG = yaml.safe_load(open("/up/matharena/configs/competitions/hmmt/hmmt_feb_2025.yaml"))
grade = grader.extract_and_grade
grader.extract_and_grade = lambda solution, gold: grade([{"role": "assistant", "content": solution}], 0, gold, CONFIG)
