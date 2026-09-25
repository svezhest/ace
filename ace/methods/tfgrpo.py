"""Training-Free GRPO (youtu-agent: utu/practice/training_free_grpo.py, experience_updater.py).
Промпты utu/prompts/practice/experience.yaml дословно в ace/prompts/tfgrpo_*.j2 (пара _sp / _up на промпт), параметры из
configs/practice/math_reasoning.yaml.

    1 память      библиотека опытов «Experience name: Brief description.»
    2 инжект      вся библиотека: «When solving problems, you MUST first carefully read ...», «[id]. опыт»
    3 сигнал      верный ответ и награда 0/1 каждой из G = 5 попыток при T = 0.7
    4 обновление  reflect: when(группа верна частично, seq(each_attempt(сводка траектории), групповое
                  преимущество -> не больше 1 опыта, сверка с библиотекой -> операции ADD / UPDATE / DELETE / NONE));
                  до конца батча библиотека не меняется, поэтому сверка идёт в reflect;
                  curate раз в батч: retry(план батча по всем операциям) -> apply_ops
    решатель      в зачёт жадная попытка при T = 0 (как оценка в апстриме), группа из 5 отдельно

Батч в апстриме 50 из 100 задач, 2 шага за эпоху; у нас 20 из 40, те же 2 шага. Неполный батч отбрасывается.
"""
from .. import curate, inject, parse, prompts, reflect
from ..feedback import Feedback
from ..loop import Method, Solver
from ..memory import Kind, Note
from ..update import Update, objectives, paired, retry, seq


# 1. память

MEMORY = {"experience": Kind(Note, ("add", "edit", "delete"))}

# 2. инжект

experiences = inject.show(line=inject.dotted, head="",
                          before=prompts.text("tfgrpo_experiences_intro"))

# 4. обновление

OBJECTIVE = {t: prompts.text(f"tfgrpo_objective_{t}") for t in ("formula", "finer", "meb", "gpqa")}
LEARNING = prompts.text("tfgrpo_learning")
NUM, BATCH = 1, 20
GOALS = objectives(OBJECTIVE, LEARNING, NUM)

summarize = paired("tfgrpo_single_rollout_summary_template", reflect.rollout_fields, GOALS)
advantage = paired("tfgrpo_single_query_group_advantage", reflect.advantage_fields, GOALS, parse=parse.enclosed("Experiences"))
against_library = paired("tfgrpo_group_experience_update_template", reflect.library_fields, GOALS, parse=reflect.nonempty_ops)

group_advantage = reflect.when(reflect.partial_group, seq(reflect.each_attempt(summarize), reflect.summarized, advantage))
plan = retry(paired("tfgrpo_batch_experience_update_template", curate.plan_fields, GOALS, parse=parse.json_block), 3)

tfgrpo = Method("tfgrpo", MEMORY, experiences, Feedback("golden"),
                Update(seq(group_advantage, against_library, reflect.as_ops), curate.planned(plan, curate.apply_ops(curate.op_list)),
                       every=BATCH),
                Solver(samples=5, temperature=0.7))
