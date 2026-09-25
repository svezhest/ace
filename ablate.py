"""Цепочка абляций: каждая ступень отличается от предыдущей одной частью.
python ablate.py TASK [N] [STEP ...]"""
import sys

from ace import bound, config, inject, prompts
from ace.env import Sandbox
from ace.loop import Solver, run, swap
from ace.methods import ace, baseline, proto
from ace.methods.ace import curate_json, curate_rewrite, curate_tools, reflect_text
from ace.methods.hybrids import hooks
from ace.methods.proto import curate_json as proto_json, curate_rewrite as proto_rewrite
from ace.model import Model
from ace.tasks import TASKS

nobound = lambda *_: None
PLACEBO = prompts.text("placebo")
CHAIN = {
    "baseline": baseline,
    "placebo": swap(baseline, inject=inject.fixed(PLACEBO)),                    # та же длина промпта без знаний
    "sc3": swap(baseline, solver=Solver(samples=2, vote=True)),                  # столько же вызовов без памяти
    "ace": ace,
    "ace_text": swap(ace, reflect=reflect_text),                         # обновление: рефлексия свободным текстом
    "ace_json": swap(ace, curate=curate_json),                           # обновление: все операции одним JSON
    "ace_rewrite": swap(ace, curate=curate_rewrite),                     # обновление: полная перезапись
    "catalog": swap(ace, inject=inject.catalog()),                              # инжект: каталог вместо всей памяти
    "typed": swap(proto, bound=nobound, curate=curate_tools),                   # память: типы; сигнал: прочитанное
    "ops5": swap(proto, bound=nobound),                                         # обновление: операции прототипа через tools
    "ops5_json": swap(proto, bound=nobound, curate=proto_json),       # операции одной схемой
    "ops5_rewrite": swap(proto, bound=nobound, curate=proto_rewrite), # все записи заново
    "gate": swap(proto, bound=bound.gate()),                                   # ограничение: gate на val
    "budget": swap(proto, bound=bound.budget(0.25)),                           # ограничение: доля бюджета
    "proto": proto,
    "code": swap(proto, solver=Solver(env=Sandbox())),                         # решатель: исполнение python
    "hooks": hooks(proto, "hooks"),                                            # хуки по ошибкам: уроки моделью
    "hooks_keep": hooks(proto, "hooks_keep", prune=None),                      # хуки не удаляются по счётчикам
    "hooks_raw": hooks(proto, "hooks_raw", learn="raw"),                       # хуки из траектории без модели (как DC)
}

task = TASKS[sys.argv[1]]
n = int(sys.argv[2]) if len(sys.argv) > 2 else config.SIZE
for name in sys.argv[3:] or CHAIN:
    print(run(task, swap(CHAIN[name], name), Model(), n, f"{config.RESULTS}/{task.name}{n}/{name}"))
