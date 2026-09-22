"""MCE (meta-context-engineering: mce/main.py, utils.py, prompts/meta_agent.py, prompts/base_agent.py).
Промпты prompts/mce_*.txt: апстрим без кодовых интерфейсов, утилит и записи навыка в файл.

    1 память      файлы context/, их заводит и правит базовый агент
    2 инжект      все файлы context/ (интерфейс get_context у апстрима пишет сам агент кодом: не делаем)
    3 сигнал      верный ответ; базовому агенту идут только итоги (question, llm_answer, target, is_correct)
    4 обновление  итерация = проход по train батчами по 20 (every, flush); reflect: keep;
                  curate: chain(iteration — в начале итерации мета-агент ask пишет SKILL.md по истории,
                  base — curate.tools: агент по навыку правит context/, итоги батча в data/ только на чтение);
                  bound: best_by_val — в конце итерации val, следующая стартует с лучшей по val
                  (строго >, при равенстве ранняя; итерация 0 — пустой контекст)
    решатель      общий

Параметры scripts/train_symptom_diagnosis.sh: 3 итерации, train 50 батчами по 25, val 20;
у нас 40 батчами по 20 и val 10. Базовому агенту апстрима доступны ещё python, call_llm и эмбеддинги.
"""
import json

from .. import bound, curate as stages, fs, inject, prompts, reflect
from ..feedback import Feedback
from ..loop import Method
from ..memory import ALL, Memory
from ..update import Update, ask, snapshot

META, BASE = prompts.load("mce_meta.txt"), prompts.load("mce_base.txt")

# 1. память

MEMORY = {"context": ALL}

# 4. обновление

BATCH, ROUNDS = 20, 30


def overview(skill):
    """Раздел «## Skill Overview» навыка."""
    lines, out, inside = skill.splitlines(), [], False
    for l in lines:
        if l.strip().lower().replace(" ", "") == "##skilloverview":
            inside = True
            continue
        if inside and l.startswith("## "):
            break
        if inside:
            out.append(l)
    text = "\n".join(out).strip()
    return "\n".join(f"  {l}" if l.strip() else "" for l in text.splitlines()) if text else "  (no '## Skill Overview' section found)"


def meta_fields(ctx, memory, deltas, history, **extra):
    done = history[1:]
    if not done:
        database = "No previous iterations (this is iteration 1, iter0 is baseline). Design an initial skill based on the task."
    else:
        database = "\n\n".join(f"### Iteration {i}\n- **Train**: {h['train']:.2%} | **Val**: {h['val']:.2%}\n"
                               f"- **Skill Overview**:\n{overview(h['skill'])}" for i, h in enumerate(done, 1))
    evaluations = json.dumps({f"iter{i}": dict(val_accuracy=h["val"], train_accuracy=h["train"])
                              for i, h in enumerate(history)}, indent=2)
    skills = "\n\n".join(f"### iter{i}/SKILL.md\n{h['skill']}" for i, h in enumerate(done, 1)) or "(none)"
    return dict(task_instruction=f"{ctx.task.system} {ctx.task.instr}", skill_database=database,
                evaluations=evaluations, skills=skills)


def new_skill(out, ctx, memory, deltas, history, **extra):
    """Пустой ответ: навык прошлой итерации."""
    done = history[1:]
    return (out or "").strip() or (done[-1]["skill"] if done else "")


meta = ask(META, meta_fields, then=new_skill)


def iteration(ctx, memory, deltas):
    """Итерация 0 — val пустой памяти; первый батч прохода открывает итерацию с новым навыком."""
    history = ctx.state.setdefault("iterations", [])
    if not history:
        history.append(dict(skill=None, train=None, val=bound.accuracy(ctx.evaluate(memory)), memory=snapshot(memory)))
    if ctx.step == len(deltas):
        history.append(dict(skill=meta(ctx, memory, deltas, history=history), train=None, val=None, memory=None))
    history[-1]["train"] = sum(bool(ep.ok) for ep in deltas) / len(deltas)


def results(deltas):
    data = Memory({"result": ("add",)})
    for ep in deltas:
        data.add(f"is_correct: {bool(ep.ok)}\nllm_answer: {ep.answer}\ntarget: {ep.target}\nquestion:\n{ep.question}")
    return data


base = stages.tools(BASE, lambda ctx, memory, deltas: dict(
    task_instruction=f"{ctx.task.system} {ctx.task.instr}", skill=ctx.state["iterations"][-1]["skill"],
    summary=f"train_accuracy {sum(bool(ep.ok) for ep in deltas)}/{len(deltas)}"),
    deps=lambda memory, deltas: fs.FS({"context": fs.Mount(memory), "data": fs.Mount(results(deltas), mode="ro")}),
    rounds=ROUNDS, system="You are a context engineer working with file tools.")

mce = Method("mce", MEMORY, inject.full(inject.plain, sep="\n\n"), Feedback("golden"),
             Update(reflect.keep, stages.chain(iteration, base), bound.best_by_val(), every=BATCH, flush=True), epochs=3)
