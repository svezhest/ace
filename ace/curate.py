"""Стадия curate обновления: накопленные дельты -> правка памяти. Стадия: stage(ctx, memory, deltas).
Блок по одной дельте: block(ctx, memory, delta).

    each(*blocks)                   блоки по очереди для каждой дельты
    per_lesson(*blocks)             блоки для каждого урока каждой дельты
    limit(n, key)                   не больше n принятых за прогон (SCOPE: 20)
    consolidate(kind, key, ...)     добавление с консолидацией: похожую запись сливает модель (EvoLib)
    count                           счётчики helpful / harmful по меткам дельты (ACE)
    ask(...)                        вызов модели по промпту метода (update.ask), then применяет ответ
    add(items, ...)                 новые записи из ответа модели
    apply_ops(ops)                  операции ADD / UPDATE / DELETE / NONE (TF-GRPO; ADD-only куратор ACE)
    remember(kind, text, ...)       запись прямо из дельты или эпизода (DC-RS)
    rewrite(kind, text)             все записи вида заменяются одним текстом (DC)
    tools(prompt, fields, deps)     агент правит память инструментами: файловыми (ACE стенда, MCE) или своими (прототип)
    admit(test, block)              блок только для дельт, прошедших проверку (SCOPE: классификатор)
    chain(*stages)                  стадии по очереди"""
from . import embed, fs, update
from .update import ask, seq, when  # noqa: F401  общие блоки reflect и curate


def chain(*stages):
    def stage(ctx, memory, deltas):
        for s in stages:
            s(ctx, memory, deltas)
    return stage


def each(*blocks):
    def stage(ctx, memory, deltas):
        for d in deltas:
            for b in blocks:
                b(ctx, memory, d)
    return stage


def per_lesson(*blocks):
    """Блоки для каждого урока дельты: block(ctx, memory, lesson)."""
    def stage(ctx, memory, deltas):
        for d in deltas:
            for lesson in d.lessons:
                for b in blocks:
                    b(ctx, memory, lesson)
    return stage


def limit(n, key):
    """Не больше n принятых за прогон по ключу key(урок); пропускает prev дальше или обрывает цепочку."""
    def block(ctx, memory, lesson, prev=None, **extra):
        k = "accepted" + key(lesson)
        if ctx.state.get(k, 0) >= n:
            return None
        ctx.state[k] = ctx.state.get(k, 0) + 1
        return prev if prev is not None else lesson
    return block


def count(ctx, memory, delta):
    update.count(memory, delta.helpful, delta.harmful)


def add(items, kind=lambda x: None, text=lambda x: x, **fields):
    """then для ask: items(ответ) -> элементы; kind, text и прочие поля записи — функции от элемента."""
    def then(out, ctx, memory, delta=None, **extra):
        for x in items(out):
            memory.add(text(x), kind(x), **{k: f(x) for k, f in fields.items()})
    return then


def apply_ops(ops, missing="add"):
    """ops(ответ) -> список словарей operation / id / content; без content операция пропускается;
    UPDATE несуществующего id: missing="add" добавляет запись (TF-GRPO), "skip" пропускает."""
    def then(out, ctx, memory, delta=None, **extra):
        for p in ops(out) or []:
            op, content, id = p.get("operation", "ADD"), p.get("content", ""), str(p.get("id"))
            if not content:
                continue
            if op == "ADD" or op == "UPDATE" and not memory.get(id) and missing == "add":
                memory.add(content)
            elif op == "UPDATE" and memory.get(id):
                memory.edit(id, content)
            elif op == "DELETE" and memory.get(id):
                memory.drop(id)
    return then


def remember(kind, text, **fields):
    """Запись из дельты или эпизода: text(d) и прочие поля функциями от d (DC-RS: пара вопрос-решение)."""
    def block(ctx, memory, d):
        memory.add(text(d), kind, **{k: f(d) for k, f in fields.items()})
    return block


def rewrite(kind, text=lambda d: d):
    def block(ctx, memory, delta):
        memory.rewrite(kind, text(delta))
    return block


def tools(prompt, fields, deps, rounds, toolset=fs.TOOLS, system="You are a curator."):
    """Агент с инструментами toolset над deps(memory, delta) (fs.FS для файловых); работает, пока не ответит текстом."""
    def block(ctx, memory, delta):
        ctx.model.run(system, prompt.fill(fields(ctx, memory, delta)), tools=toolset, deps=deps(memory, delta), rounds=rounds)
    return block


def admit(test, inner):
    def block(ctx, memory, delta):
        if test(ctx, memory, delta):
            inner(ctx, memory, delta)
    return block


def duplicate_words(text, texts, overlap=0.7):
    """Дубль, если одна строка — подстрока другой или общих слов больше overlap (strategic_store SCOPE)."""
    new = text.strip().lower()
    for t in texts:
        old = t.strip().lower()
        if new in old or old in new:
            return True
        a, b = set(new.split()), set(old.split())
        if a and b and len(a & b) / max(len(a), len(b)) > overlap:
            return True
    return False


def consolidate(kind, key, threshold, merge, inherit):
    """Добавление записи вида kind с консолидацией. key(text, meta) — что сравнивается по эмбеддингу.
    Похожих (косинус строго больше threshold) нет — запись добавляется. Есть — merge(ctx, old, text) -> [(текст, meta)]:
    если результат ровно один, он наследует от старой (inherit(old, meta) -> meta), а старая уходит; если
    несколько, старая остаётся. Тексты, уже лежащие в памяти, не добавляются."""
    def add(ctx, memory, text, meta):
        same = memory.of(kind)
        near = []
        if same:
            sims = embed.embed([key(r.text, r.meta) for r in same]) @ embed.embed([key(text, meta)])[0]
            near = [same[i] for i in sims.argsort()[::-1] if sims[i] > threshold]
        if not near:
            memory.add(text, kind, meta=meta)
            return
        old = near[0]
        merged = merge(ctx, old, text)
        if len(merged) == 1:
            merged = [(t, inherit(old, m)) for t, m in merged]
            memory.drop(old.id)
        for t, m in merged:
            if t not in {r.text for r in memory.of(kind)}:
                memory.add(t, kind, meta=m)
    return add
