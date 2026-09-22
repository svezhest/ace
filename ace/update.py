"""Элемент 4. Обновление: как сигнал становится правкой памяти. Память меняет только оно.

    reflect(ctx, episode, memory) -> дельта или None     память не трогает
    curate(ctx, memory, deltas)                           применяет накопленные дельты раз в every задач
    bound(ctx, memory, before)                            ограничение после правки; before = память до неё

ctx: model, task, evaluate(memory) -> [(верно, обрыв)] на val, render(memory) -> что увидит решатель,
state: своё состояние обновления на прогон (инструкция куратора MCE), gated: решения gate."""
import copy
from dataclasses import dataclass, field

from pydantic import BaseModel


@dataclass
class Update:
    reflect: callable = lambda ctx, episode, memory: None
    curate: callable = lambda ctx, memory, deltas: None
    bound: callable = lambda ctx, memory, before: None
    every: int = 1
    needs_usage: bool = False   # опирается на то, что решатель прочёл: сигнал обязан это отдавать


@dataclass
class Ctx:
    model: object
    task: object
    evaluate: callable
    render: callable
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


def dedup(threshold=0.75, max_records=None):
    """Grow-and-refine из ACE: новая запись, близкая по эмбеддингу к старой (косинус >= threshold;
    на BGE-M3 перефразировки дают 0.74-0.81, разные уроки 0.4-0.67), сливается с ней:
    счётчики складываются, остаётся старая. При max_records лишние уходят по порядку добавления."""
    from . import embed

    def bound(ctx, memory, before):
        was = {r.id for r in before.records}
        old = [r for r in memory.records if r.id in was]
        new = [r for r in memory.records if r.id not in was]
        if old and new:
            sims = embed.embed([r.text for r in new]) @ embed.embed([r.text for r in old]).T
            for i, r in enumerate(new):
                j = int(sims[i].argmax())
                if sims[i][j] >= threshold:
                    old[j].helpful += r.helpful
                    old[j].harmful += r.harmful
                    memory.drop(r.id)
        if max_records:
            for r in memory.records[:-max_records]:
                memory.drop(r.id)
    return bound


def chain(*bounds):
    def bound(ctx, memory, before):
        for b in bounds:
            b(ctx, memory, before)
    return bound


def snapshot(memory):
    return copy.deepcopy(memory)
