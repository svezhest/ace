"""Стадия curate обновления: накопленные дельты -> правка памяти. Стадия: stage(ctx, memory, deltas).
Блок по одной дельте: block(ctx, memory, delta). Вызов модели — update.ask с полями и then отсюда.

Обёртки
    chain(*stages)                  стадии по очереди
    each(*blocks)                   блоки по очереди для каждой дельты
    per_lesson(*blocks)             блоки для каждого урока каждой дельты
    admit(test, block)              блок только для дельт, прошедших проверку; has_lessons
    limit(n, key)                   не больше n принятых за прогон (SCOPE: 20)
    planned(plan, then)             один план на весь батч, затем then (TF-GRPO)
    by_label                        промпт по тому, была ли метка у эпизода (ACE)

Правки
    count                           счётчики helpful / harmful по меткам дельты (ACE)
    add(items, ...)                 новые записи из ответа модели
    apply_ops(ops)                  операции ADD / UPDATE / DELETE / NONE (TF-GRPO; ACE стенда одной схемой: Ops, op_dicts)
    remember(kind, text, ...)       запись прямо из дельты или эпизода (DC-RS)
    rewrite(kind, text)             все записи вида заменяются одним текстом (DC); rewrite_first — ответом модели
    tools(prompt, fields, deps)     агент правит память инструментами: файловыми (memory_files; ACE стенда, MCE)
                                    или операциями прототипа (TYPED_TOOLS над memory_itself)
    consolidate(kind, key, ...)     добавление с консолидацией: похожую запись сливает модель (EvoLib)

Что видит куратор: lessons_fields(view), view — files_view, text_view, entries_view

Плейбук ACE: playbook_stats, playbook_fields, Curation, additions, in_section
Классификатор SCOPE: Classification, classify_fields, settle, accepted, add_tactical, promotable, promote
План батча TF-GRPO: plan_fields, op_list
Библиотека EvoLib: condition, add_insight, add_skill, gains (лучшее решение задачи — в скрытом виде best)
Итерации MCE: meta_fields, new_skill, iteration (история — скрытый вид iterations), skill_fields, context_and_results
Прототип: TYPED_TOOLS, TypedOps, apply_typed, Entries, replace_entries, add_episode"""
import json
from dataclasses import asdict
from typing import Literal

from pydantic import BaseModel
from pydantic_ai import RunContext

from . import bound, embed, fs, parse, update
from .memory import Forbidden, Kind, Memory, needs, perspective_kind, slug
from .reflect import Lesson, Typed, best_solution

# обёртки


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


def admit(test, inner):
    def block(ctx, memory, delta):
        if test(ctx, memory, delta):
            inner(ctx, memory, delta)
    return block


def has_lessons(ctx, memory, d):
    return bool(d.lessons)


def limit(n, key):
    """Не больше n принятых за прогон по ключу key(урок); пропускает prev дальше или обрывает цепочку."""
    def block(ctx, memory, lesson, prev=None, **extra):
        k = "accepted" + key(lesson)
        if ctx.state.get(k, 0) >= n:
            return None
        ctx.state[k] = ctx.state.get(k, 0) + 1
        return prev if prev is not None else lesson
    return block


def planned(plan, then):
    """plan(ctx, memory, deltas) по всему батчу, затем then(план, ctx, memory)."""
    def stage(ctx, memory, deltas):
        then(plan(ctx, memory, deltas), ctx, memory)
    return stage


def by_label(labeled, unlabeled):
    return lambda memory, d, **extra: labeled if d.info["labeled"] else unlabeled

# правки


@needs("helpful", "harmful")
def count(ctx, memory, delta):
    update.count(memory, delta.helpful, delta.harmful)


def add(items, kind=lambda x: None, text=lambda x: x, **fields):
    """then для ask: items(ответ) -> элементы; kind, text и прочие поля записи — функции от элемента."""
    @needs(*fields)
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


class Op(BaseModel):
    op: Literal["ADD", "UPDATE"]
    text: str
    id: str = ""


class Ops(BaseModel):
    ops: list[Op]


def op_dicts(r):
    return [dict(operation=o.op, id=o.id, content=o.text) for o in (r.ops if r else [])]


def remember(kind, text, **fields):
    """Запись из дельты или эпизода: text(d) и прочие поля функциями от d (DC-RS: пара вопрос-решение)."""
    @needs(*fields, kinds=(kind,))
    def block(ctx, memory, d):
        memory.add(text(d), kind, **{k: f(d) for k, f in fields.items()})
    return block


def rewrite(kind, text=lambda d: d):
    @needs(kinds=(kind,))
    def block(ctx, memory, delta):
        memory.rewrite(kind, text(delta))
    return block


def rewrite_first(new, ctx, memory, d, **extra):
    """then: ответ модели заменяет все записи первого вида схемы."""
    return new and memory.rewrite(next(iter(memory.schema)), new.strip())


def tools(prompt, fields, deps, rounds, toolset=fs.TOOLS, system="You are a curator."):
    """Агент с инструментами toolset над deps(memory, delta) (fs.FS для файловых); работает, пока не ответит текстом."""
    def block(ctx, memory, delta):
        ctx.model.run(system, prompt.fill(fields(ctx, memory, delta)), tools=toolset, deps=deps(memory, delta), rounds=rounds)
    return block


def memory_files(memory, d):
    return fs.FS({"memory": fs.Mount(memory)})


def memory_itself(memory, d):
    return memory


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
    """Добавление записи вида kind с консолидацией. key(text, поля) — что сравнивается по эмбеддингу.
    Похожих (косинус строго больше threshold) нет — запись добавляется. Есть — merge(ctx, old, text) -> [(текст, поля)]:
    если результат ровно один, он наследует от старой (inherit(old, поля) -> поля), а старая уходит; если
    несколько, старая остаётся. Тексты, уже лежащие в памяти, не добавляются."""
    @needs(kinds=(kind,))
    def add(ctx, memory, text, values):
        same = memory.of(kind)
        near = []
        if same:
            sims = embed.embed([key(r.text, asdict(r)) for r in same]) @ embed.embed([key(text, values)])[0]
            near = [same[i] for i in sims.argsort()[::-1] if sims[i] > threshold]
        if not near:
            memory.add(text, kind, **values)
            return
        old = near[0]
        merged = merge(ctx, old, text)
        if len(merged) == 1:
            merged = [(t, inherit(old, v)) for t, v in merged]
            memory.drop(old.id)
        for t, v in merged:
            if t not in {r.text for r in memory.of(kind)}:
                memory.add(t, kind, **v)
    return add

# что видит куратор


def lessons_fields(view):
    return lambda ctx, memory, d, **extra: dict(lessons=d.shown(), memory=view(memory))


def files_view(memory):
    return "\n".join(f"memory/{r.id}: {r.text}" for r in memory.of()) or "(empty)"


def text_view(memory):
    return memory.text() or "(empty)"


@needs("when", kinds=("constraint", "procedure", "insight"))
def entries_view(memory):
    shown = "\n".join(f"[{r.id}] ({r.kind}; when: {r.when}) {r.text}" for r in memory.of("constraint", "procedure", "insight"))
    return shown or "(empty)"

# плейбук ACE


class Addition(BaseModel):
    type: str = "ADD"
    section: str = "others"
    content: str


class Curation(BaseModel):
    reasoning: str
    operations: list[Addition] = []


def playbook_stats(memory, sections):
    stats = dict(total_bullets=0, high_performing=0, problematic=0, unused=0, by_section={})
    for s in sections:
        for r in (r for r in memory.of() if r.section == slug(s)):
            stats["total_bullets"] += 1
            if r.helpful > 5 and r.harmful < 2:
                stats["high_performing"] += 1
            elif r.harmful >= r.helpful and r.harmful > 0:
                stats["problematic"] += 1
            elif r.helpful + r.harmful == 0:
                stats["unused"] += 1
            sec = stats["by_section"].setdefault(s, dict(count=0, helpful=0, harmful=0))
            sec["count"] += 1
            sec["helpful"] += r.helpful
            sec["harmful"] += r.harmful
    return stats


def playbook_fields(sections, token_budget, layout):
    """Куратор ACE видит последнюю рефлексию, вопрос, бюджет токенов, статистику и весь плейбук (layout)."""
    @needs("section", "helpful", "harmful", kinds="*")
    def fields(ctx, memory, d, **extra):
        return dict(token_budget=token_budget, current_step=ctx.step, total_samples=ctx.total,
                    playbook_stats=json.dumps(playbook_stats(memory, sections), indent=2), recent_reflection=d.lessons[-1],
                    current_playbook=layout(memory.of()), question_context=d.info["question"])
    return fields


def additions(r):
    return [op for op in (r.operations if r else []) if op.type == "ADD"]


def in_section(sections, default="others"):
    """Группа операции: раздел из списка или default."""
    return lambda op: slug(op.section) if slug(op.section) in map(slug, sections) else default

# классификатор SCOPE; урок — словарь perspective, text, rationale, confidence


class Classification(BaseModel):
    is_duplicate: bool = False
    scope: str = "tactical"
    confidence: float | None = None
    domain: str = "general"


def classify_fields(domains, intro, layout):
    """Классификатор видит strategic по доменам (layout, как get_strategic_rules_text апстрима) и tactical списком."""
    @needs(kinds=("strategic", "tactical"))
    def fields(ctx, memory, g, **extra):
        strategic = memory.of(perspective_kind("strategic", g["perspective"]))
        tactical = memory.of(perspective_kind("tactical", g["perspective"]))
        strategic_text = "\n" + intro + layout(strategic) if strategic else ""
        rules = ("\n=== STRATEGIC RULES (Cross-task, persistent): ===\n" + (strategic_text or "No strategic rules yet.")
                 + "\n\n=== TACTICAL RULES (Current task only): ===\n"
                 + ("".join(f"{i}. {r.text}\n" for i, r in enumerate(tactical, 1)) or "No tactical rules yet.\n"))
        return dict(allowed_domains=", ".join(domains), update_text=g["text"], rationale=g["rationale"],
                    initial_confidence=g["confidence"], all_rules_context=rules)
    return fields


def settle(domains):
    """Сбой классификатора: tactical с исходной confidence; домен вне списка -> general."""
    def then(c, ctx, memory, g, **extra):
        if not c:
            return Classification(confidence=g["confidence"])
        if c.confidence is None:
            c.confidence = g["confidence"]
        if c.scope == "strategic" and c.domain not in domains:
            c.domain = "general"
        return c
    return then


def accepted(threshold):
    """Не дубль и confidence не ниже порога: классификация идёт дальше, иначе цепочка обрывается."""
    return lambda ctx, memory, g, prev, **extra: prev if not prev.is_duplicate and prev.confidence >= threshold else None


@needs(kinds=("tactical",))
def add_tactical(ctx, memory, g, prev, **extra):
    memory.add(g["text"], perspective_kind("tactical", g["perspective"]))
    return prev


def promotable(threshold):
    return lambda ctx, memory, g, prev, **extra: prev.scope == "strategic" and prev.confidence >= threshold


def promote(cap, target, optimizer):
    """add_strategic_rule: без дубля по словам, домен по убыванию confidence, сверх cap — optimizer до target."""
    @needs("domain", "rationale", "confidence", kinds=("strategic",))
    def block(ctx, memory, g, prev, **extra):
        strategic = perspective_kind("strategic", g["perspective"])
        same = [r for r in memory.of(strategic) if r.domain == prev.domain]
        if duplicate_words(g["text"], [r.text for r in same]):
            return None
        rules = sorted([bound.as_rule(r) for r in same] + [dict(rule=g["text"], rationale=g["rationale"], confidence=prev.confidence)],
                       key=lambda x: -x["confidence"])
        if len(rules) > cap:
            rules = optimizer(ctx.model, rules, target)[:cap]
        bound.put_rules(memory, strategic, rules, domain=prev.domain)
        return prev
    return block

# план батча TF-GRPO


def batch_table(memory, ops):
    """Опыты с относящимися к ним операциями, затем операции без id."""
    if not ops:
        return "No batch operations."
    dump = lambda op: json.dumps(op, ensure_ascii=False, indent=2)
    out = []
    for r in memory.of():
        related = [op for op in ops if op.get("id") == r.id]
        out.append(f"Experience {r.id}:\nContent: {r.text}\n"
                   + ("Related Operations:\n" + "\n".join(map(dump, related)) if related else "No related operations."))
    loose = [op for op in ops if not op.get("id")]
    if loose:
        out.append("Operations without specific Experience ID:\n" + "\n".join(map(dump, loose)))
    return "\n\n".join(out)


def plan_fields(ctx, memory, deltas, **extra):
    return dict(experiences_and_operations=batch_table(memory, [op for d in deltas for op in d.ops if isinstance(op, dict)]))


def op_list(plan):
    return plan if isinstance(plan, list) else []

# библиотека EvoLib; дельта с info от reflect.finish


def condition(insight):
    return insight.split(", then ")[0].replace("If ", "").strip()


def add_insight(prompt, threshold):
    """insight «If ..., then ...»: сравнение по условию, слияние моделью по prompt."""
    def merge(ctx, old, text):
        out = ctx.model.one("", prompt.fill(dict(insights=f"{old.text}\n{text}"))).output or ""
        fig = []                                                        # общий список, как в апстриме
        return [(l.strip(), {"fig": fig}) for l in parse.fenced(out, "insights").splitlines() if l.strip().startswith("If ")]
    return consolidate("insight", lambda text, values: condition(text), threshold, merge,
                       inherit=lambda old, values: {"fig": old.fig})


def add_skill(prompt, threshold, rate):
    """skill по IG задачи -> блок добавления: сравнение по description, слияние моделью;
    слитая запись берёт IG как скользящее среднее с долей rate."""
    def with_gain(ig):
        def merge(ctx, old, block):
            out = ctx.model.one("", prompt.fill(dict(skills=f"{old.text}\n{block}"))).output or ""
            fig = []
            return [(b, dict(ig=ig, fig=fig, doc=d)) for b, d in parse.subtasks(out)]
        return consolidate("skill", lambda text, values: values["doc"], threshold, merge,
                           inherit=lambda old, values: dict(values, ig=rate * values["ig"] + (1 - rate) * old.ig, fig=old.fig))
    return with_gain


def gains(add_insight, add_skill):
    """insight и skills в библиотеку, лучшее решение задачи в скрытый вид best, Future IG в записи."""
    @needs("fig", kinds=("skill", "insight"))
    @needs(kinds=("best",))
    def block(ctx, memory, d):
        d = d.info
        if d["insight"]:
            add_insight(ctx, memory, d["insight"], {"fig": []})
        if d["best"]:
            b, old = d["best"], best_solution(memory, d["question"])
            if old:
                memory.edit(old.id, b["output"], score=b["score"], answer=b["answer"])
            else:
                memory.add(b["output"], "best", question=d["question"], score=b["score"], answer=b["answer"])
        for text, doc in d["skills"]:
            add_skill(d["ig"])(ctx, memory, text, dict(ig=d["ig"], fig=[], doc=doc))
        for rid, v in d["fig"]:
            if memory.get(rid):
                memory.get(rid).fig.append(v)
    return block

# итерации MCE; история — скрытый вид iterations, её же читает bound.best_by_val


def overview(skill):
    """Раздел «## Skill Overview» навыка."""
    lines, out, inside = skill.splitlines(), [], False
    for l in lines:
        if l.strip().lower().replace(" ", "") == "##skilloverview":
            inside = True
            continue
        if inside and l.startswith("## "):
            break
        if inside:
            out.append(l)
    text = "\n".join(out).strip()
    return "\n".join(f"  {l}" if l.strip() else "" for l in text.splitlines()) if text else "  (no '## Skill Overview' section found)"


def meta_fields(ctx, memory, deltas, history, **extra):
    done = history[1:]
    if not done:
        database = "No previous iterations (this is iteration 1, iter0 is baseline). Design an initial skill based on the task."
    else:
        database = "\n\n".join(f"### Iteration {i}\n- **Train**: {h.train:.2%} | **Val**: {h.val:.2%}\n"
                               f"- **Skill Overview**:\n{overview(h.text)}" for i, h in enumerate(done, 1))
    evaluations = json.dumps({f"iter{i}": dict(val_accuracy=h.val, train_accuracy=h.train)
                              for i, h in enumerate(history)}, indent=2)
    skills = "\n\n".join(f"### iter{i}/SKILL.md\n{h.text}" for i, h in enumerate(done, 1)) or "(none)"
    return dict(task_instruction=f"{ctx.task.system} {ctx.task.instr}", skill_database=database,
                evaluations=evaluations, skills=skills)


def new_skill(out, ctx, memory, deltas, history, **extra):
    """Пустой ответ: навык прошлой итерации."""
    done = history[1:]
    return (out or "").strip() or (done[-1].text if done else "")


def iteration(meta, kind="iterations"):
    """Итерация 0 — val пустой памяти; батч после закрытой итерации (с val: её закрывает конец прохода)
    открывает новую с навыком meta(..., history)."""
    @needs("train", "val", "records", kinds=(kind,))
    def stage(ctx, memory, deltas):
        if not memory.of(kind):
            memory.add("", kind, val=bound.accuracy(ctx.evaluate(memory)), records=memory.opened())
        if memory.of(kind)[-1].val is not None:
            memory.add(meta(ctx, memory, deltas, history=memory.of(kind)), kind)
        memory.edit(memory.of(kind)[-1].id, train=sum(bool(ep.ok) for ep in deltas) / len(deltas))
    return stage


@needs(kinds=("iterations",))
def skill_fields(ctx, memory, deltas, **extra):
    return dict(task_instruction=f"{ctx.task.system} {ctx.task.instr}", skill=memory.of("iterations")[-1].text,
                summary=f"train_accuracy {sum(bool(ep.ok) for ep in deltas)}/{len(deltas)}")


def results(deltas):
    data = Memory({"result": Kind(ops=("add",))})
    for ep in deltas:
        data.add(f"is_correct: {bool(ep.ok)}\nllm_answer: {ep.answer}\ntarget: {ep.target}\nquestion:\n{ep.question}")
    return data


def context_and_results(memory, deltas):
    """context/ — память на запись, data/ — итоги батча только на чтение."""
    return fs.FS({"context": fs.Mount(memory), "data": fs.Mount(results(deltas), mode="ro")})

# прототип: операции куратора над типизированной памятью; память сама не даст нарушить политику типа


def named(name):
    """Имя инструмента для модели."""
    def wrap(f):
        f.__name__ = name
        return f
    return wrap


@named("add")
@needs("when")
def add_entry(ctx: RunContext[Memory], kind: Typed, when: str, text: str) -> str:
    """Add a new entry."""
    return ctx.deps.add(text, kind=kind, when=when).id


@named("patch")
def patch_entry(ctx: RunContext[Memory], id: str, text: str) -> str:
    """Rewrite the text of a procedure or insight."""
    if not ctx.deps.get(id):
        return "no such id"
    try:
        ctx.deps.edit(id, text)
    except Forbidden:
        return "not allowed"
    return "ok"


@named("narrow")
@needs("when")
def narrow_entry(ctx: RunContext[Memory], id: str, when: str) -> str:
    """Make the applicability condition of an entry more specific."""
    if not ctx.deps.get(id):
        return "no such id"
    ctx.deps.edit(id, when=when)
    return "ok"


@named("merge")
@needs("when", "helpful", "harmful")
def merge_entries(ctx: RunContext[Memory], ids: list[str], when: str, text: str) -> str:
    """Replace several procedures or insights with one entry."""
    recs = [ctx.deps.get(i) for i in ids if ctx.deps.get(i)]
    if len(recs) < 2 or any("delete" not in ctx.deps.ops(r.kind) for r in recs):
        return "not allowed"
    keep, *rest = recs
    ctx.deps.edit(keep.id, text, when)
    keep.helpful, keep.harmful = sum(r.helpful for r in recs), sum(r.harmful for r in recs)
    for r in rest:
        ctx.deps.drop(r.id)
    return keep.id


TYPED_TOOLS = (add_entry, patch_entry, narrow_entry, merge_entries)


class TypedOp(BaseModel):
    op: Literal["add", "patch", "narrow", "merge"]
    kind: Typed = "insight"
    ids: list[str] = []
    when: str = ""
    text: str = ""


class TypedOps(BaseModel):
    ops: list[TypedOp] = []


class Deps:
    """Подстановка RunContext, когда операции применяет код, а не модель через tool."""
    def __init__(self, memory):
        self.deps = memory


@needs("when", "helpful", "harmful")
def apply_typed(r, ctx, memory, d, **extra):
    """then: операции одной схемой через те же инструменты."""
    for op in (r.ops if r else []):
        deps, id = Deps(memory), op.ids[0] if op.ids else ""
        if op.op == "add":
            add_entry(deps, op.kind, op.when, op.text)
        elif op.op == "merge":
            merge_entries(deps, op.ids, op.when, op.text)
        elif op.op == "patch":
            patch_entry(deps, id, op.text)
        else:
            narrow_entry(deps, id, op.when)


class Entry(Lesson):
    id: str = ""


class Entries(BaseModel):
    entries: list[Entry] = []


@needs("when", kinds=("constraint", "procedure", "insight"))
def replace_entries(r, ctx, memory, d, **extra):
    """then: полный новый список; оставленные по id правятся, остальные уходят; constraint не трогаются."""
    if not r:
        return
    keep = {e.id: e for e in r.entries if e.id}
    for rec in memory.of("constraint", "procedure", "insight"):
        if rec.id in keep:
            memory.edit(rec.id, keep[rec.id].text if rec.kind != "constraint" else None, keep[rec.id].when)
        elif rec.kind != "constraint":
            memory.drop(rec.id)
    for e in r.entries:
        if not e.id:
            memory.add(e.text, kind=e.kind, when=e.when)


@needs(kinds=("episode",))
def add_episode(ctx, memory, d):
    if d.episode:
        memory.add(kind="episode", **d.episode)
