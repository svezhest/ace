"""Цепочка абляций: каждая ступень отличается от предыдущей одним модулем.
python ablate.py TASK [N] [STEP ...]"""
import sys
from dataclasses import replace

from ace import bound
from ace.env import Skills
from ace.loop import Method, run
from ace.methods import ace, baseline, proto
from ace.model import Model
from ace.tasks import TASKS

nobound = lambda *_: None
CHAIN = {
    "baseline": baseline,
    "ace": ace,
    "catalog": replace(ace, inject=proto.inject, env=Skills()),                   # Inject: каталог вместо полной памяти
    "typed": replace(proto, bound=nobound, curate=ace.curate),                     # Store: типы, рефлексия по вызванным
    "ops5": replace(proto, bound=nobound),                                         # Curate: пять операций
    "gate": replace(proto, bound=bound.gate()),                                    # Bound: gate
    "budget": replace(proto, bound=bound.budget(0.25)),                            # Bound: доля бюджета
    "proto": proto,
}

task = TASKS[sys.argv[1]]
n = int(sys.argv[2]) if len(sys.argv) > 2 else 40
for name in sys.argv[3:] or CHAIN:
    print(run(task, replace(CHAIN[name], name=name), Model(), n, f"results/{task.name}{n}/{name}"))
