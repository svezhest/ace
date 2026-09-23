"""Гибриды: деталь одного метода внутри другого. Каждый отличается от ACE (или прототипа) одной заменой."""
from .. import bound, curate, inject, prompts, reflect
from ..env import Sandbox
from ..loop import Solver, swap
from ..memory import Hook, Kind
from ..update import ask, on_prev, seq, when
from .ace import ace as ACE, reflect_json
from .proto import proto as PROTO
from .scope import CAP, TARGET, optimizer
from .tfgrpo import group_advantage

SELECT, HOOK = prompts.load("hybrid_select.txt"), prompts.load("hook_reflect.txt")

# reflect ACE, но два кандидата и селектор (Best-of-N из SCOPE)
select = ask(SELECT, reflect.two_fields, system="You are a selector.", parse=reflect.one_or_two)
ace_bo2 = swap(ACE, "ace_bo2", reflect=reflect.best_of(reflect_json, 2, select, temperature=0))
# семантическое преимущество TF-GRPO по группе попыток; дальше куратор ACE
ace_group = swap(ACE, "ace_group", reflect=seq(group_advantage, on_prev(reflect.free_lessons())), solver=Solver(samples=3))
ace_opt = swap(ACE, "ace_opt", bound=bound.optimize(("bullet",), optimizer, CAP, TARGET))
proto_opt = swap(PROTO, "proto_opt", bound=bound.chain(bound.budget(0.25), bound.optimize(("insight",), optimizer, CAP, TARGET)))
# хуки по ошибкам: после задачи с ошибками инструмента модель выводит уроки с фрагментом ошибки (trigger);
# в память идут только уверенные, и в следующих задачах урок дописывается к промпту после шага с той же ошибкой
learn_hooks = when(reflect.has_failures, ask(HOOK, reflect.failure_fields, reflect.HookLessons, then=reflect.confident_hooks("high")))


def hooks(method, name):
    """Метод + хуки по ошибкам; решатель с исполнением python, иначе ошибок инструментов нет."""
    u = method.update
    return swap(method, name, memory={**method.memory, "hook": Kind(Hook, ("add", "edit"), apart=True)},
                inject=inject.hooked(method.inject, inject.triggered(), on=inject.on_failure),
                reflect=reflect.also(u.reflect, learn_hooks, "hooks"), curate=curate.chain(u.curate, curate.each(curate.add_hooks())),
                solver=Solver(env=Sandbox()))


ace_hooks, proto_hooks = hooks(ACE, "ace_hooks"), hooks(PROTO, "proto_hooks")

HYBRIDS = [ace_bo2, ace_group, ace_opt, proto_opt, ace_hooks, proto_hooks]
