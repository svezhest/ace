"""Показ EvoLib (_sample_from_library апстрима): одно случайное число на попытку выбирает ветку — p < 0.4 —
до 10 skills, p < 0.7 — до 10 insights, иначе ничего (пустая ветка отдаёт ход следующей); выборка с
возвращением по весу; к системному промпту — просьба решать подзадачами.

Вес задаёт показ, библиотека его не знает: skill — w_IG * max(IG, eps) + (среднее fig или 0.5), при w_IG от 100
без Future IG; insight — max(среднее fig или 0.5, eps)."""
from .. import prompts, render
from ..extract.evolib import EPS
from . import Choose, Hint, Part, Sample

K, W_IG = 10, 1.0
LEGACY_W_IG = 100           # при w_IG от 100 апстрим не прибавляет Future IG к весу skill («legacy defaults»)
FIG_PRIOR = 0.5             # Future IG записи, которая ещё ни разу не была в промпте лучшей попытки
P_SKILLS, P_INSIGHTS = 0.4, 0.7     # накопленные вероятности веток показа


def future(r):
    return sum(r.outcomes) / len(r.outcomes) if r.outcomes else FIG_PRIOR


def skill_weight(r, w_ig=W_IG):
    w = w_ig * max(r.ig, EPS)
    return max(w + future(r) if w_ig < LEGACY_W_IG else w, EPS)


def insight_weight(r):
    return max(future(r), EPS)


def sample(k, weight, intro):
    return Sample(k, weight, line=render.plain, head="", before=prompts.text(intro))


def show(k=K, w_ig=W_IG):
    """Выборка из библиотеки: k записей ветки, вес skill с w_ig."""
    return Hint(prompts.text("evolib_subtasks"), Choose(
        (P_SKILLS, Part(lambda m: m.skills, sample(k, lambda r: skill_weight(r, w_ig), "evolib_skills_intro"))),
        (P_INSIGHTS, Part(lambda m: m.insights, sample(k, insight_weight, "evolib_insights_intro")))))


SHOW = show()
