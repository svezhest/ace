"""Элемент 4. Обновление: как сигнал становится правкой памяти. Память меняет только оно.
Обновление подписано на события цикла:

    шаг       step(ctx, эпизод до шага, memory, step=шаг)   правка сразу, внутри прогона (SCOPE); только
                                                            при обучении, не на val и не на тесте
    задача    reflect(ctx, episode, memory) -> дельта       память не трогает                  reflect.py
    батч      раз в every задач: curate(ctx, memory, deltas) -> bound(ctx, memory, before)
                                                            правка и ограничение после неё     curate.py, bound.py
    проход    epoch(ctx, memory)                            конец прохода (MCE: flush неполного батча,
                                                            best_by_val); без epoch неполный батч отбрасывается

Стадии собираются из блоков этих модулей; общие блоки здесь: at_once — событие шага из reflect и curate без
батча, flush — неполный батч в конце прохода, chain — обработчики подряд; ask — один вызов модели по промпту метода,
paired — то же по паре промптов системный / пользовательский, seq — цепочка блоков, when — блок по условию
(иначе цепочка обрывается), maybe — блок по условию (иначе цепочка идёт дальше), on_prev — then над
результатом предыдущего блока, retry — повтор до разбора.

ctx: model, task, evaluate(memory) -> [(верно, обрыв)] на val, render(memory) -> что увидит решатель,
retry(memory, note) -> новая попытка того же вопроса с заметкой (раунды рефлексии ACE),
step и total: номер задачи в проходе и их число, state: своё состояние обновления на прогон, gated: решения gate,
pending: дельты текущего батча."""
import copy
from dataclasses import dataclass, field

from pydantic import BaseModel

from . import prompts
from .memory import needs


@dataclass
class Update:
    reflect: callable = lambda ctx, episode, memory: None
    curate: callable = lambda ctx, memory, deltas: None
    bound: callable = lambda ctx, memory, before: None
    every: int = 1
    epoch: callable = None
    step: callable = None
    needs_usage: bool = False   # опирается на то, что решатель прочёл: сигнал обязан это отдавать

    def batch(self, ctx, memory):
        if ctx.pending:
            before = snapshot(memory)
            self.curate(ctx, memory, ctx.pending)
            self.bound(ctx, memory, before)
        ctx.pending = []


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
    pending: list = field(default_factory=list)
    update: Update = None


def flush(ctx, memory):
    """Неполный батч в конце прохода применяется (MCE)."""
    ctx.update.batch(ctx, memory)


def chain(*handlers):
    def handler(*args, **extra):
        for h in handlers:
            h(*args, **extra)
    return handler


def at_once(reflect, curate):
    """Дельта reflect сразу идёт в curate, без батча (событие шага SCOPE: правило действует со следующего шага)."""
    def handler(ctx, ep, memory, **extra):
        d = reflect(ctx, ep, memory, **extra)
        if d:
            curate(ctx, memory, [d])
    return handler


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


def ask(prompt, fields, output=str, then=None, system="", temperature=0, tokens=1, parse=None):
    """Блок одного вызова модели. prompt — Prompt или функция от аргументов стадии, fields(ctx, *args, **extra)
    -> поля промпта, parse(ответ) — разбор (parse.py), then(разобранный ответ или None, ctx, *args, **extra)
    -> результат блока. system — строка или
    функция от ctx (TF-GRPO: цели агента зависят от задачи). Температуру может задать обёртка (best_of).
    tokens — множитель бюджета генерации (DC пишет cheatsheet вдвое длиннее)."""
    def block(ctx, *args, **extra):
        p = prompt(*args, **extra) if callable(prompt) else prompt
        out = ctx.model.run(system(ctx) if callable(system) else system, p.fill(fields(ctx, *args, **extra)), output=output,
                            temperature=extra.get("temperature", temperature),
                            max_tokens=tokens * ctx.model.max_tokens if tokens != 1 else None).output
        if parse:
            out = parse(out)
        return then(out, ctx, *args, **extra) if then else out
    return block


def paired(name, fields, system_fields, then=None, parse=None):
    """Пара промптов апстрима: name_sp — системный с полями system_fields(ctx), name_up — пользовательский (TF-GRPO)."""
    system = prompts.load(f"{name}_sp")
    return ask(prompts.load(f"{name}_up"), fields, system=lambda ctx: system.fill(system_fields(ctx)), then=then, parse=parse)


def objectives(agent, learning, num):
    """Поля системных промптов TF-GRPO: цель агента по задаче, цель обучения, сколько опытов за раз."""
    return lambda ctx: dict(agent_objective=agent[ctx.task.name], learning_objective=learning, num_experiences=num)


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


def on_prev(then):
    """В цепочке: then(результат предыдущего блока, ctx, *args, **extra)."""
    return lambda ctx, *args, prev=None, **extra: then(prev, ctx, *args, **extra)


@needs("helpful", "harmful")
def count(memory, helpful, harmful):
    for id in helpful:
        if memory.get(id):
            memory.get(id).helpful += 1
    for id in harmful:
        if memory.get(id):
            memory.get(id).harmful += 1


def snapshot(memory):
    return copy.deepcopy(memory)
