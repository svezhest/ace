"""Мир уроков: записи со статистикой, правка структурированными операциями, применяет их код.

    add(text)           ADD — новая запись
    update(id, text)    UPDATE — новая запись на месте старой: новый id, статистика с нуля
    delete(id)          DELETE
    apply(ops)          операции, предложенные моделью (какие операции модель вообще может предложить, решает
                        схема её ответа)
    replace(texts)      вся память заново: старые записи уходят со статистикой, новые с нуля
    prune(test)         отсев записей, для которых test(r)

Контейнеры: Lessons — список записей; Sections — разделы (каждый Lessons) с общей нумерацией. Политики метода
(отсев, слияние) — его код."""
from .record import Lesson


class Ids:
    """Нумерация записей r1, r2, ...: id не переиспользуются."""
    def __init__(self, prefix="r"):
        self.prefix = prefix
        self.n = 0

    def next(self):
        self.n += 1
        return f"{self.prefix}{self.n}"

    def order(self, id):
        return int(id[len(self.prefix):])


class Container:
    """Общее для контейнеров уроков: поиск, размер, ключ, сериализация."""
    requires = frozenset()      # добавки, которые память требует от извлечения (extract/__init__.py)

    def records(self):
        raise NotImplementedError

    def begin(self, k):
        """Новая попытка k: здесь уходят записи со сроком жизни «попытка» (tactical SCOPE)."""

    def get(self, id):
        return next((r for r in self.records() if r.id == id), None)

    def __len__(self):
        return len(self.records())

    def chars(self):
        return sum(len(r.text) for r in self.records())

    def key(self):
        """Что сравнивается, когда решают, та же ли это память (кэш val)."""
        return tuple(r.text for r in self.records())


class Lessons(Container):
    def __init__(self, kind="lesson", record=Lesson, ids=None):
        self.kind = kind
        self.record = record
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
        for proposed in ops:
            op = proposed.get("operation", "ADD")
            content = proposed.get("content", "")
            rid = str(proposed.get("id"))
            if not content:
                continue
            exists = self.get(rid) is not None
            if op == "ADD" or (op == "UPDATE" and not exists and missing == "add"):
                self.add(content)
            elif op == "UPDATE" and exists:
                self.update(rid, content)
            elif op == "DELETE" and exists:
                self.delete(rid)

    def prune(self, test):
        self.items = [r for r in self.items if not test(r)]

    def dump(self):
        return [dict(kind=self.kind, **r.dump()) for r in self.items]


class Sections(Container):
    """Разделы — контейнеры уроков с общей нумерацией; records() — все записи в порядке появления."""
    def __init__(self, names, kind="lesson", record=Lesson, ids=None):
        self.kind = kind
        self.ids = ids or Ids()
        self.sections = {name: Lessons(kind, record, self.ids) for name in names}

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
