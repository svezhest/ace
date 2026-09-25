"""Training-Free GRPO апстрима (youtu-agent: utu/practice/experience_updater.py, configs/practice/*.yaml): пары
промптов обучения (системный с целями агента и обучения, пользовательский с полями) и их вызов без параметров."""
from .. import parse, prompts
from ..model import TEXT, Call, Reader, messages
from ..tasks import variant

OBJECTIVE = {p.stem.removeprefix("tfgrpo_objective_"): prompts.text(p.stem)
             for p in prompts.PROMPTS.glob("tfgrpo_objective_*.j2")}
OBJECTIVE_ANY = prompts.text("tfgrpo_objective")
LEARNING = prompts.text("tfgrpo_learning")        # dapo — свой, дословно math_reasoning.yaml
LEARNING_DAPO = prompts.text("tfgrpo_learning_dapo")
NUM = 1                     # num_experiences_per_query
P = {n: (prompts.load(f"tfgrpo_{n}_sp"), prompts.load(f"tfgrpo_{n}_up"))
     for n in ("single_rollout_summary_template", "single_query_group_advantage", "group_experience_update_template",
               "batch_experience_update_template")}
EXPERIENCES = Reader(text=parse.enclosed("Experiences"))


def ask(ex, name, read=TEXT, **fields):
    """Пара промптов апстрима: системный с целями агента и обучения, пользовательский с полями; параметров нет."""
    sp, up = P[name]
    learning = LEARNING_DAPO if variant("tfgrpo", ex.task) == "math" else LEARNING
    system = sp.fill(agent_objective=objective(ex.task), learning_objective=learning, num_experiences=NUM)
    return ex.model.ask(Call(messages(up.fill(fields), system), {}, read)).output


def objective(task):
    """Цель агента для промптов обучения: у dapo — math_reasoning.yaml, у задач стенда — своя
    (tfgrpo_objective_<задача>), у задачи без своей — общая."""
    return OBJECTIVE.get(task.name, OBJECTIVE_ANY)
