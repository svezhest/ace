"""EvoLib апстрима (EvoLib/EvoLib: evolib_agent.py, llm_agent.py): параметры и поля промптов вызовов задачи,
LLMAgent.generate, прирост IG (compute_IG) — общее для решателя, извлечения и памяти EvoLib."""
import math

import numpy as np

from .. import prompts
from ..model import TEXT, Call, Reply, params
from ..tasks import variant

EPS = 0.01                  # пол логарифма в IG
EVOLIB = prompts.macros("evolib_strings")
# LLMAgent апстрима с reasoning API (модель задачи HMMT — o4-mini): без температуры
REASONING = {"max_completion_tokens": 50000, "reasoning_effort": "high"}
TRIES = 20                  # пустой ответ — тот же запрос заново; у апстрима без предела


def llm_params(task):
    """Параметры всех вызовов EvoLib: у hmmt — как у апстрима (reasoning API), у задач стенда — стенда (S4)."""
    return dict(REASONING) if variant("evolib", task) == "math" else params()


def domain(task):
    """Поля промптов EvoLib: у hmmt — слова апстрима, у задач стенда — без math (S2)."""
    math = variant("evolib", task) == "math"
    return dict(expert=EVOLIB.expert(math=math), math=EVOLIB.subject(math=math))


def generate(model, call):
    """LLMAgent.generate апстрима: пустой ответ — тот же запрос заново; ответ без пробелов по краям разбирает
    reader вызова."""
    for _ in range(TRIES):
        reply = model.ask(Call(call.messages, call.params, TEXT))
        text = (reply.output or "").strip()
        if text:
            break
    return Reply(call.reader.read(text), text, reply.truncated, raw=text)


def log_gain(best, scores):
    """log(best) - log(mean(scores)), оба снизу ограничены EPS."""
    return math.log(max(best, EPS)) - math.log(max(np.mean(scores), EPS))
