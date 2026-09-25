"""Извлечение EvoLib (EvoLib/EvoLib/evolib_agent.py: run_iteration; промпты evolib_*.j2) по группе попыток:

    баллы       с внешней оценкой (метка или судья, evaluated) — по вердикту попытки; без неё — по вердикту
                группы: попытка верна, если её ответ совпал с ответом большинства
    лучшая      первая с наибольшим баллом; IG = log(лучший) - log(средний), оба снизу eps (compute_IG)
    insight     модель по вопросу и лучшему решению («If ..., then ...»; N/A — нет). Без оценки — всегда, и
                если insight есть, баллы делятся пополам; с оценкой — только при неудаче лучшей, с её вердиктом

Даёт: ig (до деления баллов), best_answer (лучшее решение попытки с баллом после деления: улучшает ли оно
лучшее решение вопроса, решает память — после слияния insight, как в апстриме), attribution (записи в промпте
каждой попытки и номер лучшей — для Future IG)."""
import math
from dataclasses import dataclass

from .. import parse, prompts, render
from ..model import Call, Reader, messages, params
from . import ATTRIBUTION, BEST_ANSWER, IG, Extraction, Extractor

EPS = 0.01                  # пол логарифма в IG
UNEVALUATED = 0.5           # множитель баллов без внешней оценки, когда insight есть
INSIGHT = prompts.load("evolib_insight")


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


def log_gain(best, scores, eps=EPS):
    """log(best) - log(mean(scores)), оба снизу ограничены eps."""
    return math.log(max(best, eps)) - math.log(max(sum(scores) / len(scores), eps))


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


def insight_of(text):
    """Первый блок ```insight, иначе первый <insight>...</insight>; N/A — нет (generate_insight апстрима)."""
    insight = parse.first_fenced(text, "insight") or parse.between(text or "", "<insight>", "</insight>").replace("<insight>", "").strip()
    return "" if insight == "N/A" else insight


def second_better(judgment):
    """Сравнение решений в пользу второго: «solution 2» в первом блоке ```judgment (is_better_solution апстрима)."""
    return "solution 2" in parse.first_fenced(judgment, "judgment").lower()


class Gains(Extractor):
    gives = frozenset({IG, BEST_ANSWER, ATTRIBUTION})

    def __init__(self, evaluated=False):
        self.evaluated = evaluated

    def insight(self, ex, group, best, evaluation):
        prompt = INSIGHT.fill(question=group.question, solution=best.output, evaluation=evaluation)
        return ex.model.ask(Call(messages(prompt), params(), Reader(text=insight_of))).output

    def __call__(self, ex, group, memory):
        eps = group.episodes
        if self.evaluated:
            scores = [float(bool(e.ok)) for e in eps]
        else:
            scores = [1.0 if group.vote and e.answer == group.vote else 0.0 for e in eps]
        b = max(range(len(eps)), key=scores.__getitem__)
        best, ig, insight = eps[b], log_gain(scores[b], scores), ""
        if self.evaluated and scores[b] < 1:
            insight = self.insight(ex, group, best, render.evaluation(render.verdict(best.ok, best.target)))
        elif not self.evaluated and best.output:
            insight = self.insight(ex, group, best, "")
            if insight:
                scores = [s * UNEVALUATED for s in scores]
        return Extraction(group, [insight] if insight else [], scores,
                          {IG: ig, BEST_ANSWER: Best(best.output, best.answer, scores[b]),
                           ATTRIBUTION: Attribution([e.shown for e in eps], b)})
