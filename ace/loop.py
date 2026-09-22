"""Один цикл на все методы. Метод = четыре элемента памяти и решатель:

    1 память     схема: виды записей и разрешённые операции      memory.py
    2 инжект     что из памяти видит решатель                     inject.py
    3 сигнал     что после попытки возвращается в систему         feedback.py
    4 обновление reflect -> curate -> bound, раз в every задач    update.py

    решатель     среда задачи, число попыток, голосование, перспективы

    память -> инжект -> решатель -> сигнал -> обновление -> память
"""
import json
import os
import random
import time
from collections import Counter
from dataclasses import dataclass, field, replace
from pathlib import Path

from . import inject as injects
from .env import Env
from .feedback import Feedback
from .memory import ALL, Memory
from .tasks import final_answer
from .update import Ctx, Update, snapshot


@dataclass
class Solver:
    env: Env = field(default_factory=Env)
    samples: int = 0            # сколько ещё попыток при temperature 0.7 (группа для сигнала или голосования)
    vote: bool = False          # ответ большинством по всем попыткам (self-consistency)
    perspectives: tuple = ()    # K решений с разными установками, засчитывается лучшее


@dataclass
class Method:
    name: str
    memory: dict = field(default_factory=lambda: {"note": ALL})
    inject: callable = field(default_factory=injects.full)
    feedback: Feedback = field(default_factory=Feedback)
    update: Update = field(default_factory=Update)
    solver: Solver = field(default_factory=Solver)

    def __post_init__(self):
        if self.update.needs_usage and self.feedback.usage == "none":
            raise ValueError(f"{self.name}: обновлению нужно, что решатель прочёл, а сигнал этого не отдаёт (usage=none)")
        if self.feedback.usage == "env" and not getattr(self.inject, "reads", False):
            raise ValueError(f"{self.name}: usage=env, но инжект не даёт инструментов чтения")


def swap(method, name=None, **parts):
    """Метод с заменёнными частями: элементами (memory, inject, feedback, solver) или стадиями
    обновления (reflect, curate, bound, every). Проверки метода выполняются заново."""
    stages = {k: parts.pop(k) for k in ("reflect", "curate", "bound", "every", "needs_usage") if k in parts}
    return replace(method, name=name or method.name, update=replace(method.update, **stages), **parts)


@dataclass
class Attempt:
    """Всё, что известно об одной попытке, включая верный ответ. Обновлению идёт через сигнал."""
    question: str
    target: str
    output: str
    answer: str
    correct: bool
    truncated: bool
    steps: list
    context: str
    shown: list
    reads: list                 # что прочитано инструментами инжекта
    reported: list              # что решатель назвал сам


def solve(model, task, method, memory, item, temperature=0, hint=""):
    env, view = method.solver.env, method.inject(model, memory, item)
    self_report = method.feedback.usage == "self"
    system = task.system + env.hint + hint
    if view.text:
        system += "\n\nWhat you learned so far:\n" + view.text
    if self_report and memory.records:
        system += ("\n\nRight before the final answer line, write one line 'USED: <ids of the memory bullets "
                   "you actually relied on, comma-separated, or none>'.")
    r = model.run(system, f"{task.instr}\n\n{item['context']}", tools=env.tools + view.tools, deps=view.fs,
                  rounds=env.rounds + view.rounds, temperature=temperature)
    answer = final_answer(r.output or "")
    reported = [i for i in used_line(r.output or "") if memory.get(i)] if self_report else []
    return Attempt(item["context"], item["target"], r.text, answer, task.check(answer, item["target"]), r.truncated,
                   r.steps, view.text, view.shown, list(view.fs.reads) if view.fs else [], reported)


def used_line(text):
    """Самоотчёт ACE (bullet_ids) строкой «USED: r1, r3» в обычном ответе: решатель рассуждает так же, как у остальных методов."""
    lines = [l for l in text.splitlines() if l.strip().upper().startswith("USED:")]
    return [i.strip(" []") for i in lines[-1].split(":", 1)[1].split(",")] if lines else []


def attempt(model, task, method, memory, item):
    """Попытка, которая идёт в зачёт, и остальные попытки группы."""
    s = method.solver
    a = solve(model, task, method, memory, item, hint="\n\n" + s.perspectives[0] if s.perspectives else "")
    if s.perspectives:
        others = [solve(model, task, method, memory, item, hint="\n\n" + p) for p in s.perspectives[1:]]
        a = max([a, *others], key=lambda t: t.correct)
    group = [solve(model, task, method, memory, item, temperature=0.7) for _ in range(s.samples)]
    if s.vote:
        a.answer = Counter(t.answer for t in [a] + group).most_common(1)[0][0]
        a.correct = task.check(a.answer, a.target)
    return a, group


def run(task, method, model, n=40, out=None, split=""):
    items = task.load(split)[:n]
    random.seed(int(os.getenv("SEED", 0)))
    memory = Memory(dict(method.memory))
    item = None
    ctx = Ctx(model, task,
              evaluate=lambda m: [(t.correct, t.truncated) for t in (solve(model, task, method, m, it) for it in task.load("val"))],
              render=lambda m: method.inject(model, m, item).text)
    log, pending = [], []
    for i, item in enumerate(items):
        t0 = time.time()
        a, group = attempt(model, task, method, memory, item)
        episode = method.feedback.observe(model, a, group)
        delta = method.update.reflect(ctx, episode, memory)
        if delta:
            pending.append(delta)
        if (i + 1) % method.update.every == 0 and pending:
            before = snapshot(memory)
            method.update.curate(ctx, memory, pending)
            method.update.bound(ctx, memory, before)
            pending = []
        log.append(dict(i=i, question=a.question, target=a.target, answer=a.answer, correct=a.correct,
                        finish="length" if a.truncated else "stop", output=a.output, shown=a.shown, read=a.reads,
                        reported=a.reported, gated=ctx.gated[-1:], memory_chars=memory.chars(), sec=round(time.time() - t0, 1)))
        print(f"{task.name} {method.name} {i:3} {'+' if a.correct else '-'} "
              f"{sum(r['correct'] for r in log)}/{i + 1} mem={memory.chars()}", flush=True)
    summary = dict(task=task.name, method=method.name, model=model.name, n=len(log),
                   correct=sum(r["correct"] for r in log), truncated=sum(r["finish"] == "length" for r in log),
                   **model.usage())
    if out:
        Path(out).mkdir(parents=True, exist_ok=True)
        json.dump(log, open(f"{out}/log.json", "w"), ensure_ascii=False, indent=1)
        json.dump(summary, open(f"{out}/summary.json", "w"), indent=1)
        memory.save(f"{out}/memory.json")
    return summary
