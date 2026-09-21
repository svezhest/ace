"""Один цикл на все методы. Метод = набор функций, подменяемых по отдельности.

    вопрос -> inject(memory) -> решатель -> signal -> reflect -> curate -> bound -> memory
"""
import copy
import json
import os
import random
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from .env import Env
from .memory import Memory
from .tasks import final_answer


@dataclass
class Trace:
    """Всё, что известно об одной попытке."""
    question: str
    target: str
    output: str
    answer: str
    correct: bool
    truncated: bool
    used: list = field(default_factory=list)   # id записей, которые решатель вызвал
    group: list = field(default_factory=list)  # сэмплированные попытки того же вопроса (групповой сигнал)


@dataclass
class Method:
    name: str
    inject: callable = lambda memory: memory.text()          # память -> текст в системный промпт
    reflect: callable = lambda model, trace, memory: None    # опыт -> дельта (любой объект или None)
    curate: callable = lambda model, memory, delta: None     # дельта -> правка памяти
    bound: callable = lambda model, memory, task, method: None   # ограничение роста
    signal: str = "golden"                                   # golden | yes_no | none
    env: Env = field(default_factory=Env)                    # Env | Sandbox | Skills
    group: int = 0                                           # сколько сэмплов добавить к жадному ответу
    vote: bool = False                                       # ответ большинством по группе (self-consistency)
    every: int = 0                                           # батчевый сигнал: раз в every задач
    batch: callable = lambda model, memory, traces: None     # что делать с батчем трасс


def solve(model, task, memory, method, item, temperature=0):
    system = task.system + method.env.hint
    if memory.records:
        system += "\n\nWhat you learned so far:\n" + method.inject(memory)
    memory.used = []
    r = model.run(system, f"{task.instr}\n\n{item['context']}", tools=method.env.tools, deps=memory,
                  rounds=method.env.rounds, temperature=temperature)
    answer = final_answer(r.output or "")
    return Trace(item["context"], item["target"], r.text, answer,
                 task.check(answer, item["target"]), r.truncated, list(memory.used))


def run(task, method, model, n=40, out=None, split=""):
    items = task.load(split)[:n]
    random.seed(int(os.getenv("SEED", 0)))
    memory = Memory()
    log, traces = [], []
    for i, item in enumerate(items):
        t0 = time.time()
        trace = solve(model, task, memory, method, item)
        trace.group = [solve(model, task, memory, method, item, temperature=0.7) for _ in range(method.group)]
        if method.vote:
            trace.answer = Counter(t.answer for t in [trace] + trace.group).most_common(1)[0][0]
            trace.correct = task.check(trace.answer, trace.target)
        delta = method.reflect(model, trace, memory)
        if delta:
            memory.before = copy.deepcopy(memory.records)
            method.curate(model, memory, delta)
            method.bound(model, memory, task, method)
        traces.append(trace)
        if method.every and len(traces) % method.every == 0:
            method.batch(model, memory, traces[-method.every:])
        log.append(dict(i=i, target=trace.target, answer=trace.answer, correct=trace.correct,
                        finish="length" if trace.truncated else "stop", output=trace.output,
                        used=trace.used, gated=memory.gated[-1:], memory_chars=len(method.inject(memory)), sec=round(time.time() - t0, 1)))
        print(f"{task.name} {method.name} {i:3} {'+' if trace.correct else '-'} "
              f"{sum(r['correct'] for r in log)}/{i + 1} mem={len(method.inject(memory))}", flush=True)
    summary = dict(task=task.name, method=method.name, model=model.name, n=len(log),
                   correct=sum(r["correct"] for r in log), truncated=sum(r["finish"] == "length" for r in log),
                   **model.usage())
    if out:
        Path(out).mkdir(parents=True, exist_ok=True)
        json.dump(log, open(f"{out}/log.json", "w"), ensure_ascii=False, indent=1)
        json.dump(summary, open(f"{out}/summary.json", "w"), indent=1)
        memory.save(f"{out}/memory.json")
    return summary
