"""Training-Free GRPO (youtu-agent: utu/practice/training_free_grpo.py, experience_updater.py).
Промпты utu/prompts/practice/experience.yaml дословно в prompts/tfgrpo.yaml, параметры из
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

Y = prompts.load_yaml("tfgrpo.yaml")

# 1. память

MEMORY = {"experience": Kind(Note, ("add", "edit", "delete"))}

# 2. инжект

experiences = inject.show(line=inject.dotted, head="",
                          before="When solving problems, you MUST first carefully read and understand the helpful instructions and experiences:\n")

# 4. обновление

OBJECTIVE = {
    "formula": "input: A financial question with a formula to apply\noutput: A step-by-step reasoning process that leads to the numeric answer",
    "finer": "input: A financial text with numbered entities and a list of XBRL tags\noutput: A step-by-step reasoning process that leads to one tag per entity",
    "meb": "input: An equation with missing operators\noutput: A step-by-step reasoning process that leads to the equation with the operators filled in",
    "gpqa": "input: A multiple-choice question in physics, chemistry or biology\noutput: A step-by-step reasoning process that leads to the option letter",
}
LEARNING = "Help the agent to improve the solving capability on these questions by extracting general and concise guidelines."
NUM, BATCH = 1, 20
GOALS = objectives(OBJECTIVE, LEARNING, NUM)

summarize = paired(Y, "SINGLE_ROLLOUT_SUMMARY_TEMPLATE", reflect.rollout_fields, GOALS)
advantage = paired(Y, "SINGLE_QUERY_GROUP_ADVANTAGE", reflect.advantage_fields, GOALS, parse=parse.enclosed("Experiences"))
against_library = paired(Y, "GROUP_EXPERIENCE_UPDATE_TEMPLATE", reflect.library_fields, GOALS, parse=reflect.nonempty_ops)

group_advantage = reflect.when(reflect.partial_group, seq(reflect.each_attempt(summarize), reflect.summarized, advantage))
plan = retry(paired(Y, "BATCH_EXPERIENCE_UPDATE_TEMPLATE", curate.plan_fields, GOALS, parse=parse.json_block), 3)

tfgrpo = Method("tfgrpo", MEMORY, experiences, Feedback("golden"),
                Update(seq(group_advantage, against_library, reflect.as_ops), curate.planned(plan, curate.apply_ops(curate.op_list)),
                       every=BATCH),
                Solver(samples=5, temperature=0.7))
