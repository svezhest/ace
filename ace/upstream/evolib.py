"""EvoLib апстрима (EvoLib/EvoLib: evolib_agent.py, llm_agent.py): параметры и поля промптов вызовов задачи,
LLMAgent.generate, приросты IG и Future IG (compute_IG)."""
import math

import numpy as np

from ..model import TEXT, Call, Reply, params
from ..tasks import variant

EPS = 0.01                  # пол логарифма в IG
# LLMAgent апстрима с reasoning API (модель задачи HMMT — o4-mini): без температуры
REASONING = {"max_completion_tokens": 50000, "reasoning_effort": "high"}
TRIES = 20                  # пустой ответ — тот же запрос заново; у апстрима без предела


def llm_params(task):
    """Параметры всех вызовов EvoLib: у hmmt — как у апстрима (reasoning API), у задач стенда — стенда (S4)."""
    return dict(REASONING) if variant("evolib", task) == "math" else params()


def domain(task):
    """Поля промптов EvoLib: у hmmt — тексты апстрима (math), у задач стенда — без math (S2)."""
    return dict(expert="a math expert", math="math ") if variant("evolib", task) == "math" else dict(expert="an expert", math="")


def generate(model, call):
    """LLMAgent.generate апстрима: пустой ответ — тот же запрос заново; ответ без пробелов по краям разбирает
    reader вызова."""
    for _ in range(TRIES):
        reply = model.ask(Call(call.messages, call.params, TEXT))
        text = (reply.output or "").strip()
        if text:
            break
    return Reply(call.reader.read(text), text, reply.truncated, raw=text)


def log_gain(best, scores, eps=EPS):
    """log(best) - log(mean(scores)), оба снизу ограничены eps."""
    return math.log(max(best, eps)) - math.log(max(np.mean(scores), eps))


def future_gains(attribution, scores, eps=EPS):
    """Future IG: каждой записи, бывшей в промпте лучшей попытки (с повторами), прирост лучшего балла над
    средним по попыткам без этой записи; если таких попыток нет, записи ничего. -> [(id, прирост)]."""
    shown, b = attribution.shown, attribution.best
    out = []
    for rid in shown[b]:
        rest = [s for s, ids in zip(scores, shown) if rid not in ids]
        if rest:
            out.append((rid, log_gain(scores[b], rest, eps)))
    return out
