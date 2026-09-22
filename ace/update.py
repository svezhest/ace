"""Элемент 4. Обновление: как сигнал становится правкой памяти. Память меняет только оно.

    reflect(ctx, episode, memory) -> дельта или None     память не трогает
    curate(ctx, memory, deltas)                           применяет накопленные дельты раз в every задач прохода
    bound(ctx, memory, before)                            ограничение после правки; before = память до неё

ctx: model, task, evaluate(memory) -> [(верно, обрыв)] на val, render(memory) -> что увидит решатель,
retry(memory, note) -> новая попытка того же вопроса с заметкой (раунды рефлексии ACE),
step и total: номер задачи и их число, state: своё состояние обновления на прогон, gated: решения gate."""
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
    """Общая форма дельты ACE и прототипа: уроки плюс метки записей для счётчиков."""
    lessons: list = []          # строки или типизированные уроки
    helpful: list[str] = []
    harmful: list[str] = []
    episode: dict = {}          # запись об эпизоде для provenance: text, when

    def shown(self):
        return "\n".join(f"- {l}" for l in self.lessons)


def count(memory, helpful, harmful):
    for id in helpful:
        if memory.get(id):
            memory.get(id).helpful += 1
    for id in harmful:
        if memory.get(id):
            memory.get(id).harmful += 1


# ограничители, общие для методов

def budget(share, max_tokens=4096):
    """Память в промпте занимает не больше share бюджета генерации. Первыми уходят слабые insight, потом procedure."""
    limit = share * max_tokens * 4                        # символов, грубо 4 на токен

    def bound(ctx, memory, before):
        weak = sorted(memory.of("insight", "procedure"), key=lambda r: (r.kind == "procedure", r.helpful - r.harmful))
        while len(ctx.render(memory)) > limit and weak:
            memory.drop(weak.pop(0).id)
    return bound


def gate():
    """Правка принимается, только если на val не хуже прежней памяти: не меньше верных и не больше обрывов.
    Если решатель увидит то же самое, проверять нечего."""
    def bound(ctx, memory, before):
        if ctx.render(memory) == ctx.render(before):
            return
        after, prev = ctx.evaluate(memory), ctx.evaluate(before)
        ok = sum(c for c, _ in after) >= sum(c for c, _ in prev) and sum(t for _, t in after) <= sum(t for _, t in prev)
        if not ok:
            memory.records = before.records
        ctx.gated.append(ok)
    return bound


def chain(*bounds):
    def bound(ctx, memory, before):
        for b in bounds:
            b(ctx, memory, before)
    return bound


def snapshot(memory):
    return copy.deepcopy(memory)
