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
# хуки по ошибкам инструментов. Урок с фрагментом ошибки (trigger) дописывается к промпту после шага с той же
# ошибкой. Откуда урок: model — после задачи модель выводит уроки по ошибкам, в память идут только уверенные,
# и ей же показываются хуки, которые не помогли (их можно переписать); raw — как пары DC, без модели: ошибка
# и следующий вызов, который прошёл. Исход каждого показа — в счётчики хука; prune — хук уходит, когда вредных
# исходов не меньше prune и больше полезных.
LEARN = {"model": when(reflect.has_failures, ask(HOOK, reflect.failure_fields, reflect.HookLessons,
                                                 then=reflect.confident_hooks("high"))),
         "raw": reflect.raw_hooks}


def hooks(method, name, learn="model", prune=2):
    """Метод + хуки по ошибкам; решатель с исполнением python, иначе ошибок инструментов нет."""
    u = method.update
    cut = bound.prune(bound.more_harmful(prune), kinds=("hook",)) if prune else bound.chain()
    return swap(method, name, memory={**method.memory, "hook": Kind(Hook, ("add", "edit", "delete"), apart=True)},
                inject=inject.hooked(method.inject, inject.triggered(), on=inject.on_failure),
                reflect=reflect.also(u.reflect, hooks=LEARN[learn], fired=reflect.fired),
                curate=curate.chain(u.curate, curate.each(curate.add_hooks())), bound=bound.chain(u.bound, cut),
                solver=Solver(env=Sandbox()))


ace_hooks, proto_hooks = hooks(ACE, "ace_hooks"), hooks(PROTO, "proto_hooks")
proto_hooks_raw = hooks(PROTO, "proto_hooks_raw", learn="raw")

HYBRIDS = [ace_bo2, ace_group, ace_opt, proto_opt, ace_hooks, proto_hooks, proto_hooks_raw]
