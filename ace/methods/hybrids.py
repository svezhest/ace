"""Гибриды: деталь одного метода внутри другого. Каждый отличается от ACE (или прототипа) одной заменой."""
from .. import bound, prompts
from ..loop import Solver, swap
from ..update import Delta, ask
from .ace import ace as ACE, stand_reflect
from .proto import proto as PROTO
from .scope import MEMORY as STREAMS, curate as scope_curate, optimize, reflect as scope_reflect, streams
from .tfgrpo import group_advantage

SELECT = prompts.Prompt("""Two sets of lessons from the same attempt. Pick the set that is more specific and transferable: answer 1 or 2.

## 1
{a}

## 2
{b}""")


def best_of_2(ctx, ep, memory):
    """Reflect ACE, но два кандидата и селектор (Best-of-N из SCOPE)."""
    a, b = (stand_reflect()(ctx, ep, memory) for _ in range(2))
    if not a or not b:
        return a or b
    pick = ask(SELECT, lambda ctx, *_: dict(a=a.shown(), b=b.shown()), system="You are a selector.")(ctx) or "1"
    return b if pick.strip().startswith("2") else a


def group_reflect(ctx, ep, memory):
    """Семантическое преимущество TF-GRPO по группе попыток; дальше куратор ACE."""
    s = group_advantage(ctx, ep, memory)
    return Delta(lessons=[s]) if s else None


ace_bo2 = swap(ACE, "ace_bo2", reflect=best_of_2)
ace_group = swap(ACE, "ace_group", reflect=group_reflect, solver=Solver(samples=3))
ace_opt = swap(ACE, "ace_opt", bound=optimize(("bullet",)))
# потоки SCOPE вместо пунктов ACE: память, инжект, рефлексия и куратор SCOPE, ограничитель ACE
ace_steps = swap(ACE, "ace_steps", memory=STREAMS, inject=streams, reflect=scope_reflect(), curate=scope_curate)
proto_opt = swap(PROTO, "proto_opt", bound=bound.chain(bound.budget(0.25), optimize(("insight",))))

HYBRIDS = [ace_bo2, ace_group, ace_opt, ace_steps, proto_opt]
