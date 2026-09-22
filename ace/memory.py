"""Элемент 1. Память: какие записи бывают и что с ними разрешено делать.

Схема метода: вид записи -> разрешённые операции, или Kind(операции, per), если записи вида
живут одну задачу (per="task": тактические правила SCOPE; цикл стирает их перед новой задачей).
Показывает память инжект, меняет только обновление, и то в пределах схемы: запрещённая операция
поднимает Forbidden.

    add     новая запись
    edit    новый текст (и условие применения)
    narrow  только условие применения
    delete  удаление

Помощники схем: perspectives — своя копия видов на каждую перспективу (SCOPE K=2), slug — имя группы
из заголовка раздела (ACE).
"""
import json
from dataclasses import dataclass, field, asdict

ALL = ("add", "edit", "narrow", "delete")


class Forbidden(Exception):
    pass


@dataclass(frozen=True)
class Kind:
    ops: tuple = ALL
    per: str = "run"           # run | task


def perspectives(schema, names):
    """Виды «вид:перспектива» для каждой перспективы."""
    return {f"{kind}:{p}": ops for p in names for kind, ops in schema.items()}


def perspective_kind(base, perspective):
    return f"{base}:{perspective}" if perspective else base


def slug(name):
    return name.lower().strip().replace(" ", "_").replace("&", "and")


@dataclass
class Record:
    id: str
    text: str
    kind: str
    when: str = ""             # когда применять
    group: str = ""            # раздел или домен внутри вида (ACE, SCOPE)
    helpful: int = 0
    harmful: int = 0
    meta: dict = field(default_factory=dict)   # что ещё метод хранит о записи (веса, история)


@dataclass
class Memory:
    schema: dict = field(default_factory=lambda: {"note": ALL})
    records: list = field(default_factory=list)
    counter: int = 0

    def ops(self, kind):
        spec = self.schema.get(kind, ())
        return spec.ops if isinstance(spec, Kind) else spec

    def allow(self, kind, op):
        if op not in self.ops(kind):
            raise Forbidden(f"{op} is not allowed for {kind} entries")

    def new_task(self):
        """Записи видов, живущих одну задачу, уходят без операции delete: это срок жизни, а не правка."""
        self.records = [r for r in self.records if getattr(self.schema.get(r.kind), "per", "run") != "task"]

    def add(self, text, kind=None, **fields):
        kind = kind or next(iter(self.schema))
        self.allow(kind, "add")
        self.counter += 1
        rec = Record(f"r{self.counter}", text, kind, **fields)
        self.records.append(rec)
        return rec

    def edit(self, id, text=None, when=None):
        rec = self.get(id)
        if text is not None:
            self.allow(rec.kind, "edit")
            rec.text = text
        if when is not None:
            if "edit" not in self.ops(rec.kind):
                self.allow(rec.kind, "narrow")
            rec.when = when
        return rec

    def drop(self, id):
        self.allow(self.get(id).kind, "delete")
        self.records = [r for r in self.records if r.id != id]

    def rewrite(self, kind, text):
        """Все записи вида заменяются одним текстом (Dynamic Cheatsheet, MCE)."""
        old = self.of(kind)
        if len(old) == 1:
            return self.edit(old[0].id, text)
        for r in old:
            self.drop(r.id)
        return self.add(text, kind)

    def get(self, id):
        return next((r for r in self.records if r.id == id), None)

    def of(self, *kinds):
        return [r for r in self.records if not kinds or r.kind in kinds]

    def text(self, *kinds):
        return "\n".join(f"[{r.id}] {r.text}" for r in self.of(*kinds))

    def chars(self):
        return sum(len(r.text) for r in self.records)

    def save(self, path):
        json.dump([asdict(r) for r in self.records], open(path, "w"), ensure_ascii=False, indent=1)
