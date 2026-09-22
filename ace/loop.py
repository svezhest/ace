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
    samples: int = 0            # сколько ещё попыток (группа для сигнала или голосования)
    temperature: float = 0.7    # температура дополнительных попыток
    vote: bool = False          # ответ большинством по всем попыткам (self-consistency)
    perspectives: tuple = ()    # K решений, у каждого своя часть памяти; засчитывается лучшее
    hint: str = ""              # добавка метода к системному промпту решателя (формат ответа)


@dataclass
class Method:
    name: str
    memory: dict = field(default_factory=lambda: {"note": ALL})
    inject: callable = field(default_factory=injects.full)
    feedback: Feedback = field(default_factory=Feedback)
    update: Update = field(default_factory=Update)
    solver: Solver = field(default_factory=Solver)
    epochs: int = 1             # проходов по train по умолчанию, как в апстриме

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
    perspective: str = ""


def solve(model, task, method, memory, item, temperature=0, note=""):
    env, view = method.solver.env, method.inject(model, memory, item)
    self_report = method.feedback.usage == "self"
    system = task.system + env.hint + method.solver.hint
    if view.text:
        system += "\n\n" + view.head + view.text
    if self_report and memory.records:
        system += ("\n\nRight before the final answer line, write one line 'USED: <ids of the memory bullets "
                   "you actually relied on, comma-separated, or none>'.")
    user = f"{task.instr}\n\n{item['context']}" + (f"\n\nReflection:\n{note}" if note else "")
    r = model.run(system, user, tools=env.tools + view.tools, deps=view.fs,
                  rounds=env.rounds + view.rounds, temperature=temperature)
    answer = final_answer(r.output or "")
    reported = [i for i in used_line(r.output or "") if memory.get(i)] if self_report else []
    return Attempt(item["context"], item["target"], r.text, answer, task.check(answer, item["target"]), r.truncated,
                   r.steps, view.text, view.shown, list(view.fs.reads) if view.fs else [], reported,
                   item.get("perspective", ""))


def used_line(text):
    """Самоотчёт ACE (bullet_ids) строкой «USED: r1, r3» в обычном ответе: решатель рассуждает так же, как у остальных методов."""
    lines = [l for l in text.splitlines() if l.strip().upper().startswith("USED:")]
    return [i.strip(" []") for i in lines[-1].split(":", 1)[1].split(",")] if lines else []


def attempt(model, task, method, memory, item):
    """Попытка, которая идёт в зачёт, и остальные попытки (группа)."""
    s = method.solver
    if s.perspectives:
        # у каждой перспективы своя память (SCOPE K=2): инжект и обновление читают item["perspective"]
        tried = [solve(model, task, method, memory, dict(item, perspective=p)) for p in s.perspectives]
        a = max(tried, key=lambda t: t.correct)
        group = [t for t in tried if t is not a]
    else:
        a, group = solve(model, task, method, memory, item), []
    group += [solve(model, task, method, memory, item, temperature=s.temperature) for _ in range(s.samples)]
    if s.vote:
        a.answer = majority([a] + group)
        a.correct = task.check(a.answer, a.target)
    return a, group


def majority(attempts):
    """Самый частый непустой ответ; при равенстве первый встреченный."""
    votes = Counter(t.answer for t in attempts if t.answer)
    return votes.most_common(1)[0][0] if votes else ""


def run(task, method, model, n=40, out=None, split="", epochs=None, offline=False):
    """Онлайн: поток split, память обновляется по ходу, epochs проходов, в зачёт последний.
    Офлайн (ACE offline, MCE): обучение на train, после каждого прохода val, затем split
    с лучшей по val памятью без обновлений."""
    random.seed(int(os.getenv("SEED", 0)))
    epochs = epochs or method.epochs
    memory = Memory(dict(method.memory))
    item = None
    scores = {}

    def evaluate(m):
        """(верно, обрыв) на val; одна и та же память не считается дважды."""
        key = tuple((r.kind, r.text, r.when) for r in m.records)
        if key not in scores:
            scores[key] = [(t.correct, t.truncated) for t in (solve(model, task, method, m, it) for it in task.load("val"))]
        return scores[key]

    ctx = Ctx(model, task, evaluate=evaluate,
              render=lambda m: method.inject(model, m, item).text,
              retry=lambda m, note: solve(model, task, method, m, item, note=note))
    log, pending = [], []

    def record(phase, epoch, i, a, t0):
        log.append(dict(phase=phase, epoch=epoch, i=i, question=a.question, target=a.target, answer=a.answer,
                        correct=a.correct, finish="length" if a.truncated else "stop", output=a.output, shown=a.shown,
                        read=a.reads, reported=a.reported, gated=ctx.gated[-1:], memory_chars=memory.chars(),
                        sec=round(time.time() - t0, 1)))
        done = [r for r in log if r["phase"] == phase and r["epoch"] == epoch]
        print(f"{task.name} {method.name} {phase}{epoch} {i:3} {'+' if a.correct else '-'} "
              f"{sum(r['correct'] for r in done)}/{len(done)} mem={memory.chars()}", flush=True)

    best, best_val = snapshot(memory), -1
    for epoch in range(epochs):
        items = task.load("train" if offline else split)[:n]
        for i, item in enumerate(items):
            t0 = time.time()
            ctx.step, ctx.total = i + 1, len(items)
            a, group = attempt(model, task, method, memory, item)
            episode = method.feedback.observe(model, a, group)
            delta = method.update.reflect(ctx, episode, memory)
            if delta:
                pending.append(delta)
            last = i == len(items) - 1
            if ((i + 1) % method.update.every == 0 or last and method.update.flush) and pending:
                before = snapshot(memory)
                method.update.curate(ctx, memory, pending)
                method.update.bound(ctx, memory, before)
            if (i + 1) % method.update.every == 0 or last:
                pending = []            # неполный батч в конце прохода без flush отбрасывается
            record("train" if offline else "online", epoch, i, a, t0)
        if offline:
            score = sum(c for c, _ in ctx.evaluate(memory))
            print(f"val after epoch {epoch}: {score}", flush=True)
            if score > best_val:
                best, best_val = snapshot(memory), score
    if offline:
        memory = best
        for i, item in enumerate(task.load(split)[:n]):
            t0 = time.time()
            record("test", 0, i, attempt(model, task, method, memory, item)[0], t0)
    final = [r for r in log if r["phase"] == "test" or r["phase"] == "online" and r["epoch"] == epochs - 1]
    summary = dict(task=task.name, method=method.name, model=model.name, n=len(final), epochs=epochs, offline=offline,
                   correct=sum(r["correct"] for r in final), truncated=sum(r["finish"] == "length" for r in final),
                   **model.usage())
    if out:
        Path(out).mkdir(parents=True, exist_ok=True)
        json.dump(log, open(f"{out}/log.json", "w"), ensure_ascii=False, indent=1)
        json.dump(summary, open(f"{out}/summary.json", "w"), indent=1)
        memory.save(f"{out}/memory.json")
    return summary
