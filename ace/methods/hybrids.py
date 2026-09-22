"""Гибриды: модуль одного метода внутри другого. Каждый отличается от ACE ровно одной заменой."""
from dataclasses import replace

from .. import bound
from . import scope, tfgrpo
from .ace import ace as ACE, reflect as ace_reflect
from .proto import proto as PROTO

SELECT = """Two sets of lessons from the same attempt. Pick the set that is more specific and transferable: answer 1 or 2.

## 1
{a}

## 2
{b}"""


def best_of_2(model, trace, memory):
    """Reflect ACE, но два кандидата при temperature 0.7 и селектор (Best-of-N из SCOPE)."""
    a, b = (ace_reflect()(model, trace, memory) for _ in range(2))
    if not a or not b:
        return a or b
    pick = model.one("You are a selector.", SELECT.format(a="\n".join(a), b="\n".join(b))).output or "1"
    return b if pick.strip().startswith("2") else a


def group_reflect(model, trace, memory):
    """Сигнал по группе из TF-GRPO: чем верные попытки отличались от неверных; уроки идут в куратор ACE."""
    s = tfgrpo.advantage(model, trace, memory)
    return [s] if s else None


def scope_optimize(model, memory, *_):
    """Ограничитель из SCOPE: при переполнении LLM убирает конфликты и дубли."""
    for r in memory.records:
        r.kind = "tactical" if r.kind == "insight" else r.kind
    scope.bound(model, memory)
    for r in memory.records:
        r.kind = "insight" if r.kind == "tactical" else r.kind


ace_bo2 = replace(ACE, name="ace_bo2", reflect=best_of_2)
ace_group = replace(ACE, name="ace_group", reflect=group_reflect, group=3)
ace_opt = replace(ACE, name="ace_opt", bound=scope_optimize)
ace_steps = replace(ACE, name="ace_steps", reflect=scope.reflect, curate=scope.curate, inject=scope.inject)  # память ACE, рефлексия и потоки SCOPE
proto_opt = replace(PROTO, name="proto_opt", bound=bound.chain(bound.budget(0.25), scope_optimize))

HYBRIDS = [ace_bo2, ace_group, ace_opt, ace_steps, proto_opt]
