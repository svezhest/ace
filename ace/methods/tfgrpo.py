"""Training-Free GRPO (youtu-agent: utu/practice/training_free_grpo.py, experience_updater.py).
Промпты utu/prompts/practice/experience.yaml дословно в prompts/tfgrpo.yaml, параметры из
configs/practice/math_reasoning.yaml.

    1 память      библиотека опытов «Experience name: Brief description.»
    2 инжект      вся библиотека: «When solving problems, you MUST first carefully read ...», «[id]. опыт»
    3 сигнал      верный ответ и награда 0/1 каждой из G = 5 попыток при T = 0.7
    4 обновление  только группы с частично верными попытками: сводка каждой траектории (с верным ответом),
                  по сводкам групповое семантическое преимущество, не больше 1 опыта на вопрос;
                  опыт сверяется с библиотекой (ADD / UPDATE / DELETE / NONE); раз в батч операции
                  всего батча сводятся в одну правку библиотеки
    решатель      в зачёт жадная попытка при T = 0 (как оценка в апстриме), группа из 5 отдельно

Батч в апстриме 50 из 100 задач, 2 шага за эпоху; у нас 20 из 40, те же 2 шага.
"""
import json
from pathlib import Path

import jinja2
import yaml

from ..feedback import Feedback
from ..inject import View
from ..loop import Method, Solver
from ..update import Update

PROMPTS = yaml.safe_load((Path(__file__).parent / "prompts" / "tfgrpo.yaml").read_text())

# 1. память

MEMORY = {"experience": ("add", "edit", "delete")}

# 2. инжект


def experiences(model, memory, item):
    if not memory.records:
        return View()
    text = ("When solving problems, you MUST first carefully read and understand the helpful instructions and experiences:\n"
            + "\n".join(f"[{r.id}]. {r.text}" for r in memory.records))
    return View(text, [r.id for r in memory.records], head="")

# 4. обновление

OBJECTIVE = {
    "formula": "input: A financial question with a formula to apply\noutput: A step-by-step reasoning process that leads to the numeric answer",
    "finer": "input: A financial text with numbered entities and a list of XBRL tags\noutput: A step-by-step reasoning process that leads to one tag per entity",
    "meb": "input: An equation with missing operators\noutput: A step-by-step reasoning process that leads to the equation with the operators filled in",
    "gpqa": "input: A multiple-choice question in physics, chemistry or biology\noutput: A step-by-step reasoning process that leads to the option letter",
}
LEARNING = "Help the agent to improve the solving capability on these questions by extracting general and concise guidelines."
NUM, BATCH = 1, 20


def ask(ctx, name, **values):
    """Системная и пользовательская части промпта апстрима: name_SP и name_UP."""
    render = lambda part, **v: jinja2.Template(PROMPTS[f"{name}_{part}"]).render(**v)
    sp = render("SP", agent_objective=OBJECTIVE[ctx.task.name], learning_objective=LEARNING, num_experiences=NUM)
    return ctx.model.one(sp, render("UP", **values)).output


def json_block(text):
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


def advantage(ctx, ep):
    """Сводки траекторий группы и групповое преимущество; возвращает текст новых опытов или None."""
    labeled, answer = bool(ep.target), ep.target or "[REDACTED]"
    if not partial(ep.group, labeled):
        return None
    summarized = [(g, ask(ctx, "SINGLE_ROLLOUT_SUMMARY_TEMPLATE", question=ep.question, trajectory=g.output,
                          answer=answer, critique="[No critique provided]")) for g in ep.group]
    summarized = [(g, s) for g, s in summarized if s]
    if not partial([g for g, _ in summarized], labeled):
        return None
    trajectories = "\n\n".join(f"Attempt {i + 1} (Reward {float(bool(g.ok)) if labeled else '[REDACTED]'}):\n{s}"
                               for i, (g, s) in enumerate(summarized))
    critique = ask(ctx, "SINGLE_QUERY_GROUP_ADVANTAGE", question=ep.question, answer=answer, trajectories=trajectories)
    if critique is None:
        return None
    low = critique.lower()
    if "<experiences>" in low and "</experiences>" in low:
        start = low.index("<experiences>") + len("<experiences>")
        return critique[start:low.index("</experiences>", start)].strip()
    return ""


def reflect(ctx, ep, memory):
    """Опыты вопроса сверяются с библиотекой; до конца батча библиотека не меняется."""
    new = advantage(ctx, ep)
    if new is None:
        return None
    existing = "\n".join(f"[{r.id}]. {r.text}" for r in memory.records) or "None"
    ops = json_block(ask(ctx, "GROUP_EXPERIENCE_UPDATE_TEMPLATE", existing_experiences=existing, new_experiences=new))
    return ops if isinstance(ops, list) else None


def curate(ctx, memory, deltas):
    ops = [op for d in deltas for op in d if isinstance(op, dict)]
    plan = []
    for _ in range(3):
        plan = json_block(ask(ctx, "BATCH_EXPERIENCE_UPDATE_TEMPLATE", experiences_and_operations=table(memory, ops)))
        if plan is not None:
            break
    for p in plan if isinstance(plan, list) else []:
        op, content, id = p.get("operation", "ADD"), p.get("content", ""), str(p.get("id"))
        if not content:
            continue
        if op == "ADD" or op == "UPDATE" and not memory.get(id):
            memory.add(content)
        elif op == "UPDATE":
            memory.edit(id, content)
        elif op == "DELETE" and memory.get(id):
            memory.drop(id)


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


tfgrpo = Method("tfgrpo", MEMORY, experiences, Feedback("golden"), Update(reflect, curate, every=BATCH),
                Solver(samples=5, temperature=0.7))
