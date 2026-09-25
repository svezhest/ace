"""Training-Free GRPO апстрима (youtu-agent: utu/practice/experience_updater.py, configs/practice/*.yaml): пары
промптов обучения (системный с целями агента и обучения, пользовательский с полями) и их вызов без параметров."""
from dataclasses import dataclass

from .. import prompts
from ..model import TEXT, Call, messages
from ..tasks import variant

OBJECTIVE = {p.stem.removeprefix("tfgrpo_objective_"): prompts.text(p.stem)
             for p in prompts.PROMPTS.glob("tfgrpo_objective_*.j2")}
OBJECTIVE_ANY = prompts.text("tfgrpo_objective")
LEARNING = prompts.text("tfgrpo_learning")        # dapo — свой, дословно math_reasoning.yaml
LEARNING_DAPO = prompts.text("tfgrpo_learning_dapo")
NUM = 1                     # num_experiences_per_query


@dataclass(frozen=True)
class Stage:
    """Стадия обучения апстрима: пара промптов (<стадия>_SP системный, <стадия>_UP пользовательский)."""
    name: str               # имя пары у апстрима, строчными
    system: object
    user: object


def stage(name):
    return Stage(name, prompts.load(f"tfgrpo_{name}_sp"), prompts.load(f"tfgrpo_{name}_up"))


SUMMARY = stage("single_rollout_summary_template")          # сводка попытки
ADVANTAGE = stage("single_query_group_advantage")           # групповое преимущество
GROUP_UPDATE = stage("group_experience_update_template")    # сверка опыта группы с библиотекой
BATCH_UPDATE = stage("batch_experience_update_template")    # план батча


def ask_stage(ex, stage, read=TEXT, **fields):
    """Стадия апстрима: системный промпт с целями агента и обучения, пользовательский с полями; параметров нет."""
    learning = LEARNING_DAPO if variant("tfgrpo", ex.task) == "math" else LEARNING
    system = stage.system.fill(agent_objective=objective(ex.task), learning_objective=learning, num_experiences=NUM)
    return ex.model.ask(Call(messages(stage.user.fill(**fields), system), {}, read)).output


def objective(task):
    """Цель агента для промптов обучения: у dapo — math_reasoning.yaml, у задач стенда — своя
    (tfgrpo_objective_<задача>), у задачи без своей — общая."""
    return OBJECTIVE.get(task.name, OBJECTIVE_ANY)
