"""Гибриды: деталь одного метода внутри другого. Каждый отличается от ACE (или прототипа) одной заменой."""
from .. import bound, inject, prompts, reflect
from ..env import Sandbox
from ..loop import Solver, swap
from ..update import ask, on_prev, seq
from .ace import ace as ACE, reflect_json
from .proto import proto as PROTO
from .scope import CAP, TARGET, optimizer
from .tfgrpo import group_advantage

SELECT = prompts.load("hybrid_select.txt")

# reflect ACE, но два кандидата и селектор (Best-of-N из SCOPE)
select = ask(SELECT, reflect.two_fields, system="You are a selector.", parse=reflect.one_or_two)
ace_bo2 = swap(ACE, "ace_bo2", reflect=reflect.best_of(reflect_json, 2, select, temperature=0))
# семантическое преимущество TF-GRPO по группе попыток; дальше куратор ACE
ace_group = swap(ACE, "ace_group", reflect=seq(group_advantage, on_prev(reflect.free_lessons())), solver=Solver(samples=3))
ace_opt = swap(ACE, "ace_opt", bound=bound.optimize(("bullet",), optimizer, CAP, TARGET))
proto_opt = swap(PROTO, "proto_opt", bound=bound.chain(bound.budget(0.25), bound.optimize(("insight",), optimizer, CAP, TARGET)))
# хук на отбивку: после шага с ошибкой инструмента решатель получает тела трёх записей, ближайших к тексту ошибки
RELATED = inject.show(("procedure", "insight"), pick=inject.topk(3, query=inject.step_error), line=inject.dashed,
                      before="Entries related to the last error:\n", head="")
proto_hook = swap(PROTO, "proto_hook", inject=inject.hooked(PROTO.inject, RELATED, on=inject.on_failure),
                  solver=Solver(env=Sandbox()))

HYBRIDS = [ace_bo2, ace_group, ace_opt, proto_opt, proto_hook]
