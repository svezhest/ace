"""Элемент 2. Инжект: как память доходит до решателя.

Вариант: inject(model, memory, item) -> View. View это текст в системный промпт и, если память
читается по вызову, инструменты чтения. Память инжект не меняет. Вариант с инструментами
помечен reads = True: только он может дать сигнал «что решатель прочёл»."""
from dataclasses import dataclass, field

from . import embed, fs


@dataclass
class View:
    text: str = ""                              # в системный промпт
    shown: list = field(default_factory=list)   # id записей, попавших в промпт
    tools: tuple = ()                           # чтение памяти по вызову
    fs: object = None                           # FS, к которой привязаны инструменты
    rounds: int = 0                             # сколько лишних шагов агенту на чтение


def numbered(records):
    return "\n".join(f"[{r.id}] {r.text}" for r in records)


def dashed(records):
    return "\n".join(f"- {r.text}" for r in records)


def plain(records):
    return "\n\n".join(r.text for r in records)


def full(render=numbered, kinds=()):
    """Все записи указанных видов целиком."""
    def inject(model, memory, item):
        recs = memory.of(*kinds)
        return View(render(recs), [r.id for r in recs])
    return inject


def fixed(text):
    """Один и тот же текст независимо от памяти (плацебо)."""
    return lambda model, memory, item: View(text)


def topk(k, render=numbered, kinds=()):
    """Только k записей, ближайших по эмбеддингу к вопросу."""
    def inject(model, memory, item):
        recs = memory.of(*kinds)
        picked = [recs[i] for i in embed.top(item["context"], [r.text for r in recs], k)]
        return View(render(picked), [r.id for r in picked])
    return inject


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
            text += "Rules:\n" + (dashed(rules) or "(none)") + "\n\n"
        skills = fs.FS({"skills": fs.Mount(memory, listed, "ro", track=True)})
        text += "Entries you can read with read(path):\n" + fs.listing(skills, "skills")
        return View(text, [r.id for r in rules], fs.READ_TOOLS, skills, rounds=3)
    inject.reads = True
    return inject
