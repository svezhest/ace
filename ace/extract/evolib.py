"""Извлечение EvoLib (EvoLib/EvoLib/evolib_agent.py: run_iteration; промпты evolib_*.j2) по группе попыток:

    баллы       с внешней оценкой (метка или судья, evaluated) — по вердикту попытки; без неё — по вердикту
                группы: попытка верна, если её ответ совпал с ответом большинства
    лучшая      первая с наибольшим баллом; IG = log(лучший) - log(средний), оба снизу eps (compute_IG)
    insight     модель по вопросу и лучшему решению («If ..., then ...»; N/A — нет). Без оценки — всегда, и
                если insight есть, баллы делятся пополам; с оценкой — только при неудаче лучшей, с её вердиктом
    улучшение   лучшего решения вопроса ещё нет или оно строго хуже по баллу (после деления); без оценки, если
                старое решение не сходится с ответом большинства, решает сравнение решений моделью

Даёт: ig (до деления баллов), best_answer (лучшее решение, если оно улучшает, иначе None; skills память
берёт из него), attribution (записи в промпте каждой попытки и номер лучшей — для Future IG). Лучшее
решение вопроса память хранит скрытым от решателя (memory.best(вопрос)); извлечение читает его для
сравнения."""
import math
from dataclasses import dataclass

from .. import parse, prompts, render
from . import ATTRIBUTION, BEST_ANSWER, IG, Extraction, Extractor

EPS = 0.01                  # пол логарифма в IG
UNEVALUATED = 0.5           # множитель баллов без внешней оценки, когда insight есть
P = {n: prompts.load(f"evolib_{n}") for n in ("insight", "compare")}


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
        return insight_of(ex.model.run("", P["insight"].fill(question=group.question, solution=best.output,
                                                            evaluation=evaluation)).output)

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
        before = memory.best(group.question)
        improving = before is None or scores[b] > before.score
        if not improving and not self.evaluated and group.vote and not ex.task.check(before.answer, group.vote):
            judgment = ex.model.run("", P["compare"].fill(question=group.question, a=before.output, b=best.output)).output
            improving = second_better(judgment)
        return Extraction(group, [insight] if insight else [], scores,
                          {IG: ig, BEST_ANSWER: Best(best.output, best.answer, scores[b]) if improving else None,
                           ATTRIBUTION: Attribution([e.shown for e in eps], b)})
