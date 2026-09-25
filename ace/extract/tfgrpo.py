"""Извлечение TF-GRPO — контраст попыток группы (youtu-agent: utu/practice/experience_updater.py; промпты
tfgrpo_*.j2 дословно, пара системный / пользовательский):

    сводка каждой попытки (_single_rollout_summary)
    -> групповое преимущество по сводкам с наградами 0/1 (_group_advantage): не больше NUM опытов в <Experiences>
    -> сверка с библиотекой (_group_update): операции ADD / UPDATE / DELETE / NONE в ```json

Попытки для обучения — все, кроме той, что в зачёт (она — итоговый агент, как оценка апстрима), и без
пустой траектории (апстрим отбрасывает rollout без trajectories). С верным ответом в работу идёт только группа,
где верна часть попыток: до сводок и после них. Сводка выпадает, только если модель не ответила (исключение
у апстрима); пустая сводка остаётся. Все вызовы — без температуры, как у апстрима (model_params = {}).
Библиотека до конца батча не меняется, поэтому сверка идёт здесь, а план батча — в памяти метода
(methods/tfgrpo.py). Группа без опыта даёт пустые операции: план батча апстрим строит всегда."""
from .. import parse, prompts, render
from . import OPERATIONS, Extraction, Extractor, scores

OBJECTIVE = {t: prompts.text(f"tfgrpo_objective_{t}") for t in ("formula", "finer", "meb", "gpqa")}
LEARNING = prompts.text("tfgrpo_learning")
NUM = 1                     # num_experiences_per_query
P = {n: (prompts.load(f"tfgrpo_{n}_sp"), prompts.load(f"tfgrpo_{n}_up"))
     for n in ("single_rollout_summary_template", "single_query_group_advantage", "group_experience_update_template",
               "batch_experience_update_template")}
EXPERIENCES = parse.enclosed("Experiences")


def ask(ex, name, **fields):
    """Пара промптов апстрима: системный с целями агента и обучения, пользовательский с полями."""
    sp, up = P[name]
    system = sp.fill(agent_objective=OBJECTIVE[ex.task.name], learning_objective=LEARNING, num_experiences=NUM)
    return ex.model.run(system, up.fill(fields), temperature=None).output


def partial(rollouts, labeled):
    """С меткой в работу идут только группы, где верна часть попыток."""
    if not labeled:
        return bool(rollouts)
    mean = sum(bool(e.ok) for e in rollouts) / len(rollouts) if rollouts else 0
    return 0 < mean < 1


def rollouts(group):
    return [e for i, e in enumerate(group.episodes) if i != group.chosen and e.output]


def operations(text):
    """Непустой список операций из ```json; иначе ничего."""
    ops = parse.json_block(text)
    return ops if isinstance(ops, list) and ops else []


class Contrast(Extractor):
    """library=False — только групповое преимущество, без сверки с библиотекой: непустой опыт уходит уроком в
    чужую память (ace_group, куратор ACE), операций нет."""
    def __init__(self, library=True):
        self.library = library
        self.gives = frozenset({OPERATIONS}) if library else frozenset()

    def __call__(self, ex, group, memory):
        labeled, answer = bool(group.target), group.target or render.REDACTED
        eps, lessons, ops = rollouts(group), [], []
        if partial(eps, labeled):
            summaries = [(e, ask(ex, "single_rollout_summary_template", question=e.question, trajectory=e.output,
                                 answer=answer, critique=render.NO_CRITIQUE)) for e in eps]
            summaries = [(e, s) for e, s in summaries if s is not None]
            if partial([e for e, _ in summaries], labeled):
                found = EXPERIENCES(ask(ex, "single_query_group_advantage", question=group.question, answer=answer,
                                        trajectories=render.attempts(summaries, labeled)))
                if found is not None and not self.library:
                    lessons = [found] if found else []
                elif found is not None:
                    lessons = [found]
                    ops = operations(ask(ex, "group_experience_update_template",
                                         existing_experiences=render.experiences(memory.records()), new_experiences=found))
        return Extraction(group, lessons, scores(group), {OPERATIONS: ops} if self.library else {})
