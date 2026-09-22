"""Гибриды: деталь одного метода внутри другого. Каждый отличается от ACE (или прототипа) одной заменой."""
from .. import update
from ..loop import Solver, swap
from .scope import MEMORY as STREAMS, curate as scope_curate, optimize, reflect as scope_reflect, streams
from .ace import ace as ACE, reflect as ace_reflect
from .proto import proto as PROTO
from .tfgrpo import advantage
from ..update import Delta

SELECT = """Two sets of lessons from the same attempt. Pick the set that is more specific and transferable: answer 1 or 2.

## 1
{a}

## 2
{b}"""


def best_of_2(ctx, ep, memory):
    """Reflect ACE, но два кандидата и селектор (Best-of-N из SCOPE)."""
    a, b = (ace_reflect()(ctx, ep, memory) for _ in range(2))
    if not a or not b:
        return a or b
    pick = ctx.model.one("You are a selector.", SELECT.format(a=a.shown(), b=b.shown())).output or "1"
    return b if pick.strip().startswith("2") else a


def group_reflect(ctx, ep, memory):
    """Семантическое преимущество TF-GRPO по группе попыток; дальше куратор ACE."""
    s = advantage(ctx, ep, memory)
    return Delta(lessons=[s]) if s else None


ace_bo2 = swap(ACE, "ace_bo2", reflect=best_of_2)
ace_group = swap(ACE, "ace_group", reflect=group_reflect, solver=Solver(samples=3))
ace_opt = swap(ACE, "ace_opt", bound=optimize(("bullet",)))
# потоки SCOPE вместо пунктов ACE: память, инжект, рефлексия и куратор SCOPE, ограничитель ACE
ace_steps = swap(ACE, "ace_steps", memory=STREAMS, inject=streams, reflect=scope_reflect, curate=scope_curate)
proto_opt = swap(PROTO, "proto_opt", bound=update.chain(update.budget(0.25), optimize(("insight",))))

HYBRIDS = [ace_bo2, ace_group, ace_opt, ace_steps, proto_opt]
