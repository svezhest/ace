"""Один цикл на все методы. Метод = набор функций, подменяемых по отдельности.

    вопрос -> inject(memory) -> решатель -> signal -> reflect -> curate -> bound -> memory
"""
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

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


@dataclass
class Method:
    name: str
    inject: callable = lambda memory: memory.text()          # память -> текст в системный промпт
    reflect: callable = lambda model, trace, memory: None    # опыт -> дельта (любой объект или None)
    curate: callable = lambda model, memory, delta: None     # дельта -> правка памяти
    bound: callable = lambda model, memory: None             # ограничение роста
    signal: str = "golden"                                   # golden | yes_no | none


def solve(model, task, memory, method, item):
    system = task.system + ("\n\nWhat you learned so far:\n" + method.inject(memory) if memory.records else "")
    reply = model.one(system, f"{task.instr}\n\n{item['context']}")
    answer = final_answer(reply.text)
    return Trace(item["context"], item["target"], reply.text, answer,
                 task.check(answer, item["target"]), reply.truncated)


def run(task, method, model, n=40, out=None, split=""):
    items = task.load(split)[:n]
    memory = Memory()
    log = []
    for i, item in enumerate(items):
        t0 = time.time()
        trace = solve(model, task, memory, method, item)
        delta = method.reflect(model, trace, memory)
        if delta:
            method.curate(model, memory, delta)
            method.bound(model, memory)
        log.append(dict(i=i, target=trace.target, answer=trace.answer, correct=trace.correct,
                        finish="length" if trace.truncated else "stop", output=trace.output,
                        used=trace.used, memory_chars=len(memory.text()), sec=round(time.time() - t0, 1)))
        print(f"{task.name} {method.name} {i:3} {'+' if trace.correct else '-'} "
              f"{sum(r['correct'] for r in log)}/{i + 1} mem={len(memory.text())}", flush=True)
    summary = dict(task=task.name, method=method.name, model=model.name, n=len(log),
                   correct=sum(r["correct"] for r in log), truncated=sum(r["finish"] == "length" for r in log),
                   **model.usage())
    if out:
        Path(out).mkdir(parents=True, exist_ok=True)
        json.dump(log, open(f"{out}/log.json", "w"), ensure_ascii=False, indent=1)
        json.dump(summary, open(f"{out}/summary.json", "w"), indent=1)
        memory.save(f"{out}/memory.json")
    return summary
