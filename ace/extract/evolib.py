"""Извлечение EvoLib (EvoLib/EvoLib/evolib_agent.py: run_iteration; промпты evolib_*.j2) по группе попыток:

    баллы       с внешней оценкой (метка или судья, evaluated) — по вердикту попытки; без неё — по вердикту
                группы: попытка верна, если её ответ совпал с ответом большинства
    лучшая      первая с наибольшим баллом; IG = log(лучший) - log(средний), оба снизу eps (compute_IG)
    insight     модель по вопросу и лучшему решению («If ..., then ...»; N/A — нет). Без оценки — всегда, и
                если insight есть, баллы делятся пополам; с оценкой — только при неудаче лучшей, с её вердиктом

Даёт: ig (до деления баллов), best_answer (лучшее решение попытки с баллом после деления: улучшает ли оно
лучшее решение вопроса, решает память — после слияния insight, как в апстриме), attribution (записи в промпте
каждой попытки и номер лучшей — для Future IG).

Все вызовы EvoLib идут через generate (LLMAgent.generate апстрима) с параметрами llm_params задачи."""
from dataclasses import dataclass


from .. import parse, prompts, render
from ..model import Call, Reader, messages
from ..upstream.evolib import domain, generate, llm_params, log_gain
from . import ATTRIBUTION, BEST_ANSWER, IG, Extraction, Extractor

UNEVALUATED = 0.5           # множитель баллов без внешней оценки, когда insight есть
INSIGHT = prompts.load("evolib_insight")
STAND = prompts.macros("stand")


@dataclass
class Best:
    """Лучшее решение вопроса: весь ответ решателя, его ответ и балл."""
    output: str
    answer: str
    score: float


@dataclass
class Attribution:
    shown: list                 # id записей в промпте каждой попытки, с повторами выборки
    best: int                   # номер лучшей попытки


def insight_of(text):
    """Первый блок ```insight, иначе первый <insight>...</insight>; N/A — нет (generate_insight апстрима)."""
    insight = parse.first_fenced(text, "insight") or parse.between(text or "", "<insight>", "</insight>").replace("<insight>", "").strip()
    return "" if insight == "N/A" else insight


class Gains(Extractor):
    gives = frozenset({IG, BEST_ANSWER, ATTRIBUTION})

    def __init__(self, evaluated=False):
        self.evaluated = evaluated

    def insight(self, ex, group, best, evaluation):
        prompt = INSIGHT.fill(question=group.question, solution=best.output, evaluation=evaluation, **domain(ex.task))
        return generate(ex.model, Call(messages(prompt), llm_params(ex.task), Reader(text=insight_of))).output

    def __call__(self, ex, group, memory):
        eps = group.episodes
        if self.evaluated:
            scores = [float(bool(e.ok)) for e in eps]
        else:
            scores = [1.0 if group.vote and e.answer == group.vote else 0.0 for e in eps]
        b = max(range(len(eps)), key=scores.__getitem__)
        best, ig, insight = eps[b], log_gain(scores[b], scores), ""
        if self.evaluated and scores[b] < 1:
            insight = self.insight(ex, group, best, STAND.evaluation(verdict=render.verdict(best.ok, best.target)))
        elif not self.evaluated and best.output:
            insight = self.insight(ex, group, best, "")
            if insight:
                scores = [s * UNEVALUATED for s in scores]
        return Extraction(group, [insight] if insight else [], scores,
                          {IG: ig, BEST_ANSWER: Best(best.output, best.answer, scores[b]),
                           ATTRIBUTION: Attribution([e.shown for e in eps], b)})
