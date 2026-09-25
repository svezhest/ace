"""Мир уроков: записи со статистикой, правка структурированными операциями, применяет их код.

    add(text)           ADD — новая запись
    update(id, text)    UPDATE — новая запись на месте старой: новый id, статистика с нуля
    delete(id)          DELETE
    apply(ops)          операции, предложенные моделью; запрещённые контейнеру (ops) пропускаются
    replace(texts)      вся память заново: старые записи уходят со статистикой, новые с нуля
    count(helpful, harmful)   метки извлечения — в журналы исходов записей
    prune(test)         отсев записей, для которых test(r)

Контейнеры: Lessons — список записей; Sections — разделы (каждый Lessons) с общей нумерацией.
Права (ops) ограничивают только операции модели; политики метода (отсев, слияние) — его код."""
from enum import Flag, auto

from .record import HARMFUL, HELPFUL, Lesson


class Operation(Flag):
    ADD = auto()
    UPDATE = auto()
    DELETE = auto()


ALL = Operation.ADD | Operation.UPDATE | Operation.DELETE


class Ids:
    """Нумерация записей r1, r2, ...: id не переиспользуются."""
    def __init__(self, prefix="r"):
        self.prefix, self.n = prefix, 0

    def next(self):
        self.n += 1
        return f"{self.prefix}{self.n}"

    def order(self, id):
        return int(id[len(self.prefix):])


class Container:
    """Общее для контейнеров уроков: поиск, журнал исходов, отсев, размер, ключ, сериализация."""
    requires = frozenset()      # добавки, которые память требует от извлечения (extract/__init__.py)

    def records(self):
        raise NotImplementedError

    def begin(self, k):
        """Новая попытка k: здесь уходят записи со сроком жизни «попытка» (tactical SCOPE)."""

    def get(self, id):
        return next((r for r in self.records() if r.id == id), None)

    def __len__(self):
        return len(self.records())

    def count(self, helpful, harmful):
        for ids, outcome in ((helpful, HELPFUL), (harmful, HARMFUL)):
            for id in ids:
                if self.get(id):
                    self.get(id).outcomes.append(outcome)

    def chars(self):
        return sum(len(r.text) for r in self.records())

    def key(self):
        """Что сравнивается, когда решают, та же ли это память (кэш val)."""
        return tuple(r.text for r in self.records())


class Lessons(Container):
    def __init__(self, kind="lesson", record=Lesson, ops=ALL, ids=None):
        self.kind, self.record, self.ops = kind, record, ops
        self.ids = ids or Ids()
        self.items = []

    def records(self):
        return list(self.items)

    def add(self, text, **born):
        """born — оценка при рождении (поля класса записи метода)."""
        rec = self.record(self.ids.next(), text, **born)
        self.items.append(rec)
        return rec

    def update(self, id, text, **born):
        old = self.get(id)
        if old is None:
            return None
        rec = self.record(self.ids.next(), text, **born)
        self.items[self.items.index(old)] = rec
        return rec

    def delete(self, id):
        self.items = [r for r in self.items if r.id != id]

    def replace(self, texts):
        self.items = []
        for t in texts:
            self.add(t)

    def apply(self, ops, missing="skip"):
        """ops — словари operation / id / content (ADD / UPDATE / DELETE; прочее, например NONE, пропускается);
        без content операция пропускается. UPDATE несуществующего id: missing="add" добавляет запись, "skip" —
        пропускает."""
        for p in ops:
            op, content, id = p.get("operation", "ADD"), p.get("content", ""), str(p.get("id"))
            if not content:
                continue
            if op == "UPDATE" and not self.get(id) and missing == "add":
                op = "ADD"
            if op not in Operation.__members__ or Operation[op] not in self.ops:
                continue
            if op == "ADD":
                self.add(content)
            elif op == "UPDATE" and self.get(id):
                self.update(id, content)
            elif op == "DELETE" and self.get(id):
                self.delete(id)

    def prune(self, test):
        self.items = [r for r in self.items if not test(r)]

    def dump(self):
        return [dict(kind=self.kind, **r.dump()) for r in self.items]


class Sections(Container):
    """Разделы — контейнеры уроков с общей нумерацией; records() — все записи в порядке появления."""
    def __init__(self, names, kind="lesson", record=Lesson, ops=ALL, ids=None):
        self.kind, self.ids = kind, ids or Ids()
        self.sections = {n: Lessons(kind, record, ops, self.ids) for n in names}

    def records(self):
        return sorted((r for s in self.sections.values() for r in s.items), key=lambda r: self.ids.order(r.id))

    def section_of(self, id):
        return next((n for n, s in self.sections.items() if s.get(id)), None)

    def add(self, text, section, **born):
        return self.sections[section].add(text, **born)

    def update(self, id, text, **born):
        name = self.section_of(id)
        return self.sections[name].update(id, text, **born) if name else None

    def delete(self, id):
        for s in self.sections.values():
            s.delete(id)

    def prune(self, test):
        for s in self.sections.values():
            s.prune(test)

    def dump(self):
        return [dict(kind=self.kind, section=self.section_of(r.id), **r.dump()) for r in self.records()]
