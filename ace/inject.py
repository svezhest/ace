"""Элемент 2. Инжект: как память доходит до решателя.

Вариант: inject(model, memory, item) -> View. View это текст в системный промпт и, если память
читается по вызову, инструменты чтения. Память инжект не меняет.

Инжект собирается из блоков:
    show(kinds, pick, line | layout, before, after, empty, head)   какие записи и как они выглядят
        pick     какие из записей видов: все, topk по эмбеддингу, sample по весу (gain_weight EvoLib),
                 where по условию
        line     строка записи: plain, dashed, numbered, dotted, counted, prefixed
        layout   весь текст из записей: by_group и sections (разделы ACE, домены SCOPE), pairs (DC)
    choose((p, inject), ...)     одно случайное число выбирает ветку (EvoLib: skills, insights или ничего)
    concat(inject, ...)          несколько блоков подряд (SCOPE: strategic, затем tactical)
    synth(inject, prompt, ...)   модель переписывает показанное под вопрос (DC-RS)
    fixed(text), catalog(...)    плацебо; каталог с чтением тел по read(path)

При перспективах (SCOPE K=2) у попытки item["perspective"], и show берёт виды с этим суффиксом.
Вариант с инструментами помечен reads = True: только он может дать сигнал «что решатель прочёл»."""
import random
from dataclasses import dataclass, field, replace

from . import embed, fs
from .memory import slug

HEAD = "What you learned so far:\n"


@dataclass
class View:
    text: str = ""                              # в системный промпт
    shown: list = field(default_factory=list)   # id записей, попавших в промпт
    tools: tuple = ()                           # чтение памяти по вызову
    fs: object = None                           # FS, к которой привязаны инструменты
    rounds: int = 0                             # сколько лишних шагов агенту на чтение
    head: str = HEAD                            # заголовок перед text; у методов со своей формулировкой пуст

# строка записи


def plain(r):
    return r.text


def dashed(r):
    return f"- {r.text}"


def numbered(r):
    return f"[{r.id}] {r.text}"


def dotted(r):
    return f"[{r.id}]. {r.text}"


def counted(r):
    return f"[{r.id}] helpful={r.helpful} harmful={r.harmful} :: {r.text}"


def prefixed(prefix):
    return lambda r: prefix + r.text

# какие записи


def topk(k, key=lambda r: r.text):
    """k ближайших к вопросу по эмбеддингу, от самой близкой; близость в копии записи, meta["score"]."""
    def pick(records, item):
        sims = embed.embed([key(r) for r in records]) @ embed.embed([item["context"]])[0]
        return [replace(records[i], meta={**records[i].meta, "score": float(sims[i])}) for i in sims.argsort()[::-1][:k]]
    return pick


def sample(k, weight):
    """k записей с возвращением, с вероятностью по весу."""
    def pick(records, item):
        return random.choices(records, [weight(r) for r in records], k=min(len(records), k))
    return pick


def where(test):
    return lambda records, item: [r for r in records if test(r, item)]


def gain_weight(w_ig, eps):
    """Вес EvoLib: skill — w_IG * max(IG, eps) + (среднее FIG или 0.5), insight — max(среднее FIG или 0.5, eps).
    В апстриме у skill пола нет: отрицательный вес ломает random.choices молча, поэтому здесь пол eps."""
    def weight(r):
        fig = r.meta["fig"]
        future = sum(fig) / len(fig) if fig else 0.5
        if r.kind == "skill":
            return max(w_ig * max(r.meta["ig"], eps) + future, eps)
        return max(future, eps)
    return weight

# вид всего текста


def by_group(line, order=(), header="## {}", sep="\n\n", title=str):
    """Записи под заголовками по полю group. order — пары (группа, заголовок), показываются все,
    даже пустые; без order группы идут по первому появлению."""
    def layout(records):
        groups = list(order) or [(g, title(g)) for g in dict.fromkeys(r.group for r in records)]
        return sep.join("\n".join([header.format(t)] + [line(r) for r in records if r.group == g]) for g, t in groups)
    return layout


def titled(group):
    """tool_usage -> Tool Usage (домены SCOPE)."""
    return group.replace("_", " ").title()


def sections(names, line=counted):
    """Разделы ACE: все по порядку, даже пустые; группа записи — slug заголовка."""
    return by_group(line, order=[(slug(s), s) for s in names])


def pairs(scored, note=""):
    """Пары (вопрос в when, решение в text) в оформлении DC. scored (retrieval): с пояснением note и близостью,
    самая похожая последней; иначе (полная история) по порядку."""
    def layout(records):
        text = "### PREVIOUS SOLUTIONS (START)\n\n" + (f"{note}\n\n" if scored else "")
        for i, r in enumerate(records[::-1] if scored else records):
            if scored:
                text += (f"#### Previous Input #{i + 1} (Similarity: {r.meta['score']:.2f}):\n\n{r.when}\n\n"
                         f"#### Model Solution to Previous Input  #{i + 1}:\n\n{r.text}\n---\n---\n\n")
            else:
                text += (f"#### Previous Input #{i + 1}:\n\n{r.when}\n\n"
                         f"#### Model Solution to Previous Input #{i + 1}:\n\n{r.text}\n---\n---\n\n")
        return (text.strip() + "\n\n" if scored else text) + "#### PREVIOUS SOLUTIONS (END)"
    return layout


def text_of(memory, kind, empty):
    """Текст единственной записи вида или empty (DC: cheatsheet)."""
    return memory.of(kind)[0].text if memory.of(kind) else empty

# сборка


def kinds_of(kinds, item):
    p = (item or {}).get("perspective", "")
    return tuple(f"{k}:{p}" for k in kinds) if p and kinds else kinds


def show(kinds=(), pick=None, line=numbered, sep="\n", layout=None, before="", after="", empty=None, head=HEAD):
    """Записи видов kinds (все, если не заданы). empty: текст при пустой выборке, иначе в промпт ничего."""
    def inject(model, memory, item):
        recs = memory.of(*kinds_of(kinds, item))
        if pick and recs:
            recs = pick(recs, item)
        if not recs:
            return View(empty, head=head) if empty is not None else View()
        body = layout(recs) if layout else sep.join(line(r) for r in recs)
        return View(before + body + after, [r.id for r in recs], head=head)
    return inject


def full(line=numbered, kinds=(), sep="\n"):
    """Все записи видов kinds целиком."""
    return show(kinds, line=line, sep=sep)


def fixed(text):
    """Один и тот же текст независимо от памяти (плацебо)."""
    return lambda model, memory, item: View(text)


def choose(*branches):
    """branches: (накопленная вероятность, inject). Первая ветка, чей порог выше случайного числа и чей
    показ не пуст; иначе ничего (EvoLib: пустая библиотека skills отдаёт ход insights)."""
    def inject(model, memory, item):
        p = random.random()
        for bound, branch in branches:
            if p < bound:
                view = branch(model, memory, item)
                if view.shown:
                    return view
        return View()
    return inject


def concat(*injects, sep=""):
    def inject(model, memory, item):
        views = [v for v in (i(model, memory, item) for i in injects) if v.text]
        if not views:
            return View()
        return View(sep.join(v.text for v in views), [i for v in views for i in v.shown], head=views[0].head)
    return inject


def synth(base, prompt, fields, parse, max_tokens=2):
    """Модель переписывает показанное base под вопрос: fields(view, memory, item) -> поля промпта,
    parse(ответ) -> текст или None (тогда решатель видит сам base). max_tokens — доля от бюджета модели."""
    def inject(model, memory, item):
        view = base(model, memory, item)
        out = parse(model.one("", prompt.fill(fields(view, memory, item)), max_tokens=max_tokens * model.max_tokens).text)
        return replace(view, text=out if out is not None else view.text)
    return inject


def pairs_and_sheet(kind, empty):
    """Поля синтеза DC-RS: показанные пары, следующий вопрос, прошлый cheatsheet."""
    return lambda view, memory, item: {"PREVIOUS_INPUT_OUTPUT_PAIRS": view.text, "NEXT_INPUT": item["context"],
                                       "PREVIOUS_CHEATSHEET": text_of(memory, kind, empty)}


def catalog(always=(), listed=()):
    """Записи видов always целиком в промпте; видов listed только путь и условие применения,
    тело по read(path) из skills/, смонтированного только на чтение. Чтения отслеживаются."""
    def inject(model, memory, item):
        rules = memory.of(*always) if always else []
        entries = [r for r in memory.of(*listed) if r not in rules]
        if not rules and not entries:
            return View()
        text = ""
        if always:
            text += "Rules:\n" + ("\n".join(dashed(r) for r in rules) or "(none)") + "\n\n"
        skills = fs.FS({"skills": fs.Mount(memory, listed, "ro", track=True)})
        text += "Entries you can read with read(path):\n" + fs.listing(skills, "skills")
        return View(text, [r.id for r in rules], fs.READ_TOOLS, skills, rounds=3)
    inject.reads = True
    return inject
