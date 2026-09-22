"""Цепочка абляций: каждая ступень отличается от предыдущей одной частью.
python ablate.py TASK [N] [STEP ...]"""
import os
import sys

from ace import bound, inject
from ace.loop import Solver, run, swap
from ace.methods import ace, baseline, proto
from ace.methods.ace import stand_curate as ace_curate, stand_reflect as ace_reflect
from ace.methods.proto import curate as proto_curate
from ace.model import Model
from ace.tasks import TASKS

nobound = lambda *_: None
PLACEBO = "\n".join(f"[r{i}] Read the question carefully and check units before answering." for i in range(1, 9))
CHAIN = {
    "baseline": baseline,
    "placebo": swap(baseline, inject=inject.fixed(PLACEBO)),                    # та же длина промпта без знаний
    "sc3": swap(baseline, solver=Solver(samples=2, vote=True)),                  # столько же вызовов без памяти
    "ace": ace,
    "ace_text": swap(ace, reflect=ace_reflect("text")),                         # обновление: рефлексия свободным текстом
    "ace_json": swap(ace, curate=ace_curate("json")),                           # обновление: все операции одним JSON
    "ace_rewrite": swap(ace, curate=ace_curate("rewrite")),                     # обновление: полная перезапись
    "catalog": swap(ace, inject=inject.catalog()),                              # инжект: каталог вместо всей памяти
    "typed": swap(proto, bound=nobound, curate=ace_curate()),                   # память: типы; сигнал: прочитанное
    "ops5": swap(proto, bound=nobound),                                         # обновление: операции прототипа через tools
    "ops5_json": swap(proto, bound=nobound, curate=proto_curate("json")),       # операции одной схемой
    "ops5_rewrite": swap(proto, bound=nobound, curate=proto_curate("rewrite")), # все записи заново
    "gate": swap(proto, bound=bound.gate()),                                   # ограничение: gate на val
    "budget": swap(proto, bound=bound.budget(0.25)),                           # ограничение: доля бюджета
    "proto": proto,
}

task = TASKS[sys.argv[1]]
n = int(sys.argv[2]) if len(sys.argv) > 2 else 40
for name in sys.argv[3:] or CHAIN:
    print(run(task, swap(CHAIN[name], name), Model(), n, f"{os.getenv('RESULTS', 'results')}/{task.name}{n}/{name}"))
