"""Извлечение TF-GRPO — контраст попыток группы (youtu-agent: utu/practice/experience_updater.py; промпты
tfgrpo_*.j2 дословно, пара системный / пользовательский):

    сводка каждой попытки (_single_rollout_summary)
    -> групповое преимущество по сводкам с наградами 0/1 (_group_advantage): не больше NUM опытов в <Experiences>
    -> сверка с библиотекой (_group_update): операции ADD / UPDATE / DELETE / NONE в ```json

Попытки для обучения — вся группа rollout (у TF-GRPO в зачёт идёт тест итоговым агентом), у ace_stand_group — без
той, что в зачёт (scored), и без пустой траектории (апстрим отбрасывает rollout без trajectories). С верным ответом в работу идёт только группа,
где верна часть попыток: до сводок и после них. Сводка выпадает, только если модель не ответила (исключение
у апстрима); пустая сводка остаётся.
Библиотека до конца батча не меняется, поэтому сверка идёт здесь, а план батча — в памяти метода
(memory/tfgrpo.py). Группа без опыта даёт пустые операции: план батча апстрим строит всегда. Вызовы — без
параметров запроса, как у апстрима (model_params = {}: температура и предел генерации — сервера)."""
from .. import parse, render
from ..model import Reader
from ..upstream.tfgrpo import EXPERIENCES, ask
from . import OPERATIONS, Extraction, Extractor, scores

def partial(rollouts, labeled):
    """С меткой в работу идут только группы, где верна часть попыток."""
    if not labeled:
        return bool(rollouts)
    mean = sum(bool(e.ok) for e in rollouts) / len(rollouts) if rollouts else 0
    return 0 < mean < 1


def rollouts(group, scored):
    return [e for i, e in enumerate(group.episodes) if not (scored and i == group.chosen) and e.output]


def operations(text):
    """Непустой список операций из ```json; иначе ничего."""
    ops = parse.json_block(text)
    return ops if isinstance(ops, list) and ops else []


class Contrast(Extractor):
    """library=True — масштаб батча, как ExperienceUpdater.run апстрима: стадии идут по всему батчу — все сводки, все
    групповые преимущества, все сверки с библиотекой; у каждого вопроса батча своё извлечение с операциями.
    library=False — масштаб вопроса и только групповое преимущество, без сверки: непустой опыт уходит уроком в
    чужую память (ace_stand_group, куратор ACE), операций нет. scored — попытка в зачёт в группу не входит."""
    def __init__(self, library=True, scored=False):
        self.library, self.scored = library, scored
        self.gives = frozenset({OPERATIONS}) if library else frozenset()
        self.scale = "batch" if library else "question"

    def summaries(self, ex, group):
        """Сводки попыток группы; None — группа не идёт в работу. Без ответа модели сводка выпадает."""
        eps = rollouts(group, self.scored)
        if not partial(eps, bool(group.target)):
            return None
        answer = group.target or render.REDACTED
        out = [(e, ask(ex, "single_rollout_summary_template", question=e.question, trajectory=e.output, answer=answer,
                       critique=render.NO_CRITIQUE)) for e in eps]
        return [(e, s) for e, s in out if s is not None]

    def advantage(self, ex, group, summaries):
        """Опыт в <Experiences> ("" — пары тегов нет); None — группа выпала или модель не ответила."""
        labeled = bool(group.target)
        if summaries is None or not partial([e for e, _ in summaries], labeled):
            return None
        return ask(ex, "single_query_group_advantage", EXPERIENCES, question=group.question,
                   answer=group.target or render.REDACTED, trajectories=render.attempts(summaries, labeled))

    def update(self, ex, memory, found):
        return ask(ex, "group_experience_update_template", Reader(text=operations),
                   existing_experiences=render.experiences(memory.records()), new_experiences=found)

    def batch(self, ex, groups, memory):
        summaries = [self.summaries(ex, g) for g in groups]
        found = [self.advantage(ex, g, s) for g, s in zip(groups, summaries)]
        ops = [self.update(ex, memory, f) if f is not None else [] for f in found]
        return [Extraction(g, [f] if f is not None else [], scores(g), {OPERATIONS: o}) for g, f, o in zip(groups, found, ops)]

    def __call__(self, ex, group, memory):
        found = self.advantage(ex, group, self.summaries(ex, group))
        return Extraction(group, [found] if found else [], scores(group))
