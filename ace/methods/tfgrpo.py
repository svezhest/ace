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
import json

from .. import curate as stages, inject, prompts, reflect as steps
from ..feedback import Feedback
from ..loop import Method, Solver
from ..update import Delta, Update, ask, retry, seq

Y = prompts.load_yaml("tfgrpo.yaml")

# 1. память

MEMORY = {"experience": ("add", "edit", "delete")}

# 2. инжект

experiences = inject.show(line=lambda r: f"[{r.id}]. {r.text}", head="",
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


def template(name, fields, then=None):
    """Пара промптов апстрима: name_SP с целями агента и обучения — системный, name_UP — пользовательский."""
    system = lambda ctx: Y[f"{name}_SP"].fill(dict(agent_objective=OBJECTIVE[ctx.task.name], learning_objective=LEARNING,
                                                   num_experiences=NUM))
    return ask(Y[f"{name}_UP"], fields, system=system, then=then)


def json_block(text, *_, **__):
    try:
        return json.loads(text.split("```json")[-1].split("```")[0])
    except (json.JSONDecodeError, AttributeError):
        return None


def partial(rollouts, labeled):
    """С меткой в работу идут только группы, где верна часть попыток."""
    if not labeled:
        return bool(rollouts)
    mean = sum(bool(g.ok) for g in rollouts) / len(rollouts) if rollouts else 0
    return 0 < mean < 1


def answer(ep):
    return ep.target or "[REDACTED]"


summarize = template("SINGLE_ROLLOUT_SUMMARY_TEMPLATE", lambda ctx, g, memory, **_: dict(
    question=g.question, trajectory=g.output, answer=answer(g), critique="[No critique provided]"))


def summarized(ctx, ep, memory, prev, **extra):
    kept = [(g, s) for g, s in prev if s]
    return kept if partial([g for g, _ in kept], bool(ep.target)) else None


def experiences_of(critique, *_, **__):
    """Текст внутри <Experiences>, регистр не важен; без блока пусто."""
    if critique is None:
        return None
    low = critique.lower()
    if "<experiences>" in low and "</experiences>" in low:
        start = low.index("<experiences>") + len("<experiences>")
        return critique[start:low.index("</experiences>", start)].strip()
    return ""


advantage = template("SINGLE_QUERY_GROUP_ADVANTAGE", lambda ctx, ep, memory, prev, **_: dict(
    question=ep.question, answer=answer(ep), trajectories="\n\n".join(
        f"Attempt {i + 1} (Reward {float(bool(g.ok)) if ep.target else '[REDACTED]'}):\n{s}" for i, (g, s) in enumerate(prev))),
    then=experiences_of)

against_library = template("GROUP_EXPERIENCE_UPDATE_TEMPLATE", lambda ctx, ep, memory, prev, **_: dict(
    existing_experiences="\n".join(f"[{r.id}]. {r.text}" for r in memory.records) or "None", new_experiences=prev),
    then=lambda text, *_, **__: ops if isinstance(ops := json_block(text), list) and ops else None)

group_advantage = steps.when(lambda ctx, ep, memory, **_: partial(ep.group, bool(ep.target)),
                             seq(steps.each_attempt(summarize), summarized, advantage))
reflect = seq(group_advantage, against_library, lambda ctx, ep, memory, prev, **_: Delta(ops=prev))


def table(memory, ops):
    """Опыты с относящимися к ним операциями, затем операции без id."""
    if not ops:
        return "No batch operations."
    dump = lambda op: json.dumps(op, ensure_ascii=False, indent=2)
    out = []
    for r in memory.records:
        related = [op for op in ops if op.get("id") == r.id]
        out.append(f"Experience {r.id}:\nContent: {r.text}\n"
                   + ("Related Operations:\n" + "\n".join(map(dump, related)) if related else "No related operations."))
    loose = [op for op in ops if not op.get("id")]
    if loose:
        out.append("Operations without specific Experience ID:\n" + "\n".join(map(dump, loose)))
    return "\n\n".join(out)


def batch_ops(deltas):
    return [op for d in deltas for op in d.ops if isinstance(op, dict)]


plan = retry(template("BATCH_EXPERIENCE_UPDATE_TEMPLATE", lambda ctx, memory, deltas, **_: dict(
    experiences_and_operations=table(memory, batch_ops(deltas))), then=json_block), 3)


def curate(ctx, memory, deltas):
    stages.apply_ops(lambda p: p if isinstance(p, list) else [])(plan(ctx, memory, deltas), ctx, memory)


tfgrpo = Method("tfgrpo", MEMORY, experiences, Feedback("golden"), Update(reflect, curate, every=BATCH),
                Solver(samples=5, temperature=0.7))
