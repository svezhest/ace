"""Элемент 4. Обновление: как сигнал становится правкой памяти. Память меняет только оно.

    reflect(ctx, episode, memory) -> дельта или None     память не трогает              reflect.py
    curate(ctx, memory, deltas)                           применяет дельты раз в every     curate.py
    bound(ctx, memory, before)                            ограничение после правки         bound.py

Стадии собираются из блоков этих модулей; общие блоки здесь: ask — один вызов модели по промпту метода,
seq — цепочка блоков, when — блок по условию (иначе цепочка обрывается), maybe — блок по условию
(иначе цепочка идёт дальше), retry — повтор до разбора.

ctx: model, task, evaluate(memory) -> [(верно, обрыв)] на val, render(memory) -> что увидит решатель,
retry(memory, note) -> новая попытка того же вопроса с заметкой (раунды рефлексии ACE),
step и total: номер задачи в проходе и их число, state: своё состояние обновления на прогон, gated: решения gate."""
import copy
from dataclasses import dataclass, field

from pydantic import BaseModel


@dataclass
class Update:
    reflect: callable = lambda ctx, episode, memory: None
    curate: callable = lambda ctx, memory, deltas: None
    bound: callable = lambda ctx, memory, before: None
    every: int = 1
    flush: bool = False         # неполный батч в конце прохода применить; иначе он отбрасывается (TF-GRPO)
    needs_usage: bool = False   # опирается на то, что решатель прочёл: сигнал обязан это отдавать


@dataclass
class Ctx:
    model: object
    task: object
    evaluate: callable
    render: callable
    retry: callable = None
    step: int = 0
    total: int = 0
    state: dict = field(default_factory=dict)
    gated: list = field(default_factory=list)


class Delta(BaseModel):
    """Общая форма дельты: уроки, метки записей для счётчиков, предложенные операции, прочее."""
    lessons: list = []          # строки или типизированные уроки
    helpful: list[str] = []
    harmful: list[str] = []
    episode: dict = {}          # запись об эпизоде для provenance: text, when
    ops: list = []              # операции над памятью, предложенные рефлексией (TF-GRPO)
    info: dict = {}             # что ещё нужно куратору: вопрос, баллы, лучшее решение

    def shown(self):
        return "\n".join(f"- {l}" for l in self.lessons)


def ask(prompt, fields, output=str, then=None, system="", temperature=0, tokens=1):
    """Блок одного вызова модели. prompt — Prompt или функция от аргументов стадии, fields(ctx, *args, **extra)
    -> поля промпта, then(ответ или None, ctx, *args, **extra) -> результат блока. system — строка или
    функция от ctx (TF-GRPO: цели агента зависят от задачи). Температуру может задать обёртка (best_of).
    tokens — множитель бюджета генерации (DC пишет cheatsheet вдвое длиннее)."""
    def block(ctx, *args, **extra):
        p = prompt(*args, **extra) if callable(prompt) else prompt
        out = ctx.model.run(system(ctx) if callable(system) else system, p.fill(fields(ctx, *args, **extra)), output=output,
                            temperature=extra.get("temperature", temperature),
                            max_tokens=tokens * ctx.model.max_tokens if tokens != 1 else None).output
        return then(out, ctx, *args, **extra) if then else out
    return block


def retry(inner, n):
    """inner до n раз, пока результат None (TF-GRPO: разбор JSON плана батча)."""
    def block(ctx, *args, **extra):
        for _ in range(n):
            out = inner(ctx, *args, **extra)
            if out is not None:
                return out
        return None
    return block


def seq(*blocks):
    """Блоки по очереди, результат предыдущего в extra["prev"]; None обрывает цепочку."""
    def block(ctx, *args, **extra):
        out = None
        for b in blocks:
            out = b(ctx, *args, **{**extra, "prev": out})
            if out is None:
                return None
        return out
    return block


def when(test, inner):
    """inner, только если test(ctx, *args, **extra)."""
    return lambda ctx, *args, **extra: inner(ctx, *args, **extra) if test(ctx, *args, **extra) else None


def maybe(test, inner):
    """В цепочке: inner, если test(ctx, *args, **extra), иначе результат предыдущего блока дальше без изменений."""
    return lambda ctx, *args, **extra: inner(ctx, *args, **extra) if test(ctx, *args, **extra) else extra.get("prev")


def count(memory, helpful, harmful):
    for id in helpful:
        if memory.get(id):
            memory.get(id).helpful += 1
    for id in harmful:
        if memory.get(id):
            memory.get(id).harmful += 1


def snapshot(memory):
    return copy.deepcopy(memory)
