"""Цепочка абляций: каждая ступень отличается от предыдущей одним модулем.
python ablate.py TASK [N] [STEP ...]"""
import os
import sys
from dataclasses import replace

from ace import bound
from ace.env import Skills
from ace.loop import Method, run
from ace.methods import ace, baseline, proto
from ace.methods.ace import curate as ace_curate, reflect as ace_reflect
from ace.methods.proto import curate as proto_curate
from ace.model import Model
from ace.tasks import TASKS

nobound = lambda *_: None
PLACEBO = "\n".join(f"[r{i}] Read the question carefully and check units before answering." for i in range(1, 9))
CHAIN = {
    "baseline": baseline,
    "placebo": replace(baseline, inject=lambda memory: PLACEBO, reflect=lambda *_: True, curate=lambda model, memory, _: memory.records or memory.add("placebo")),
    "sc3": replace(baseline, group=2, vote=True),
    "ace": ace,
    "ace_text": replace(ace, reflect=ace_reflect("text")),                          # Reflect: свободный текст вместо схемы
    "ace_json": replace(ace, curate=ace_curate("json")),                            # Curate: все операции одним JSON
    "ace_rewrite": replace(ace, curate=ace_curate("rewrite")),                      # Curate: полная перезапись
    "catalog": replace(ace, inject=proto.inject, env=Skills()),                   # Inject: каталог вместо полной памяти
    "typed": replace(proto, bound=nobound, curate=ace.curate),                     # Store: типы, рефлексия по вызванным
    "ops5": replace(proto, bound=nobound),                                         # Curate: операции через tools
    "ops5_json": replace(proto, bound=nobound, curate=proto_curate("json")),       # Curate: операции одной схемой
    "ops5_rewrite": replace(proto, bound=nobound, curate=proto_curate("rewrite")), # Curate: все записи заново
    "gate": replace(proto, bound=bound.gate()),                                    # Bound: gate
    "budget": replace(proto, bound=bound.budget(0.25)),                            # Bound: доля бюджета
    "proto": proto,
}

task = TASKS[sys.argv[1]]
n = int(sys.argv[2]) if len(sys.argv) > 2 else 40
for name in sys.argv[3:] or CHAIN:
    print(run(task, replace(CHAIN[name], name=name), Model(), n, f"{os.getenv('RESULTS', 'results')}/{task.name}{n}/{name}"))
