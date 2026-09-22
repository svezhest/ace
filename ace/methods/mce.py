"""MCE (meta-context-engineering: mce/main.py, utils.py, prompts/meta_agent.py, prompts/base_agent.py).
Промпты prompts/mce_*.txt: апстрим без кодовых интерфейсов, утилит и записи навыка в файл.

    1 память      файлы context/, их заводит и правит базовый агент
    2 инжект      все файлы context/ (интерфейс get_context у апстрима пишет сам агент кодом: не делаем)
    3 сигнал      верный ответ; базовому агенту идут только итоги (question, llm_answer, target, is_correct)
    4 обновление  итерация = проход по train батчами: в начале итерации мета-агент по истории
                  (навыки, train и val прошлых итераций) пишет SKILL.md; после каждого батча базовый
                  агент по навыку правит context/ файловыми инструментами, читая итоги батча в data/;
                  в конце итерации val, следующая итерация стартует с лучшей по val (строго >,
                  при равенстве ранняя; итерация 0 — пустой контекст)
    решатель      общий

Параметры scripts/train_symptom_diagnosis.sh: 3 итерации, train 50 батчами по 25, val 20;
у нас 40 батчами по 20 и val 10. Базовому агенту апстрима доступны ещё python, call_llm и эмбеддинги.
"""
import copy
import json
from pathlib import Path

from .. import fs, inject
from ..feedback import Feedback
from ..loop import Method
from ..memory import ALL, Memory
from ..update import Update, snapshot

PROMPTS = Path(__file__).parent / "prompts"
META, BASE = (PROMPTS / "mce_meta.txt").read_text(), (PROMPTS / "mce_base.txt").read_text()

# 1. память

MEMORY = {"context": ALL}

# 4. обновление

BATCH, ROUNDS = 20, 30


def keep(ctx, ep, memory):
    return ep


def accuracy(results):
    return sum(c for c, _ in results) / len(results) if results else 0.0


def curate(ctx, memory, episodes):
    history = ctx.state.setdefault("iterations", [])
    if not history:
        history.append(dict(skill=None, train=None, val=accuracy(ctx.evaluate(memory)), memory=snapshot(memory)))
    if ctx.step == len(episodes):                        # первый батч прохода: новая итерация
        history.append(dict(skill=meta(ctx, history), train=None, val=None, memory=None))
    current = history[-1]
    current["train"] = sum(bool(ep.ok) for ep in episodes) / len(episodes)
    base(ctx, memory, episodes, current["skill"])
    if ctx.step == ctx.total:                            # конец итерации: val и откат к лучшей
        current["val"], current["memory"] = accuracy(ctx.evaluate(memory)), snapshot(memory)
        best = history[0]
        for h in history[1:]:
            if h["val"] > best["val"]:
                best = h
        memory.records = copy.deepcopy(best["memory"].records)
        memory.counter = max(memory.counter, best["memory"].counter)


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


def meta(ctx, history):
    done = history[1:]
    if not done:
        database = "No previous iterations (this is iteration 1, iter0 is baseline). Design an initial skill based on the task."
    else:
        database = "\n\n".join(f"### Iteration {i}\n- **Train**: {h['train']:.2%} | **Val**: {h['val']:.2%}\n"
                               f"- **Skill Overview**:\n{overview(h['skill'])}" for i, h in enumerate(done, 1))
    evaluations = json.dumps({f"iter{i}": dict(val_accuracy=h["val"], train_accuracy=h["train"])
                              for i, h in enumerate(history)}, indent=2)
    skills = "\n\n".join(f"### iter{i}/SKILL.md\n{h['skill']}" for i, h in enumerate(done, 1)) or "(none)"
    prompt = META.format(task_instruction=f"{ctx.task.system} {ctx.task.instr}", skill_database=database,
                         evaluations=evaluations, skills=skills)
    return (ctx.model.one("", prompt).output or "").strip() or (done[-1]["skill"] if done else "")


def base(ctx, memory, episodes, skill):
    data = Memory({"result": ("add",)})
    for ep in episodes:
        data.add(f"is_correct: {bool(ep.ok)}\nllm_answer: {ep.answer}\ntarget: {ep.target}\nquestion:\n{ep.question}")
    summary = f"train_accuracy {sum(bool(ep.ok) for ep in episodes)}/{len(episodes)}"
    prompt = BASE.format(task_instruction=f"{ctx.task.system} {ctx.task.instr}", skill=skill, summary=summary)
    files = fs.FS({"context": fs.Mount(memory), "data": fs.Mount(data, mode="ro")})
    ctx.model.run("You are a context engineer working with file tools.", prompt, tools=fs.TOOLS, deps=files, rounds=ROUNDS)


mce = Method("mce", MEMORY, inject.full(inject.plain), Feedback("golden"), Update(keep, curate, every=BATCH, flush=True),
             epochs=3)
