"""Элемент 1. Память: какие записи бывают и что с ними разрешено делать.

Метод объявляет память схемой: вид -> Kind(класс записи, операции, срок жизни, скрыт ли от решателя).
Класс записи задаёт её поля: у пункта ACE раздел и счётчики, у правила SCOPE домен и уверенность, у skill
EvoLib прирост, у хука — фрагмент ошибки, на который он срабатывает. Поля, которого у класса нет, нет вовсе: ни прочитать, ни записать.

    add     новая запись
    edit    новый текст или другие поля
    narrow  только условие применения (when)
    delete  удаление

Счётчики и приросты (helpful, harmful, fig) — статистика: обновление меняет их без операции.
Скрытые виды (private) решатель не видит: эпизоды прототипа, лучшие решения EvoLib, история итераций MCE.
Отдельные виды (apart) решатель видит, но не в общем показе, а только через блок, назвавший вид (хуки по ошибкам).
И те и другие берут только по имени: memory.of("episode"); memory.of() без видов отдаёт остальные (открытые).

Блоки объявляют, что им нужно от памяти: needs(поля, kinds=виды). Method при сборке сверяет это со схемой
(check), поэтому, например, ограничитель по счётчикам ACE на правилах SCOPE не соберётся.

Помощники схем: perspectives — своя копия видов на каждую перспективу (SCOPE K=2), slug — имя раздела
из заголовка (ACE).
"""
import copy
import json
from dataclasses import asdict, dataclass, field, fields

ALL = ("add", "edit", "narrow", "delete")


class Forbidden(Exception):
    pass

# записи


@dataclass(slots=True)
class Note:
    """Просто текст: опыт TF-GRPO, cheatsheet DC, файл контекста MCE, тактическое правило SCOPE."""
    id: str
    text: str
    kind: str

    def head(self):
        """Строка в каталоге."""
        return self.text.splitlines()[0][:80] if self.text else ""

    def key(self):
        """Что сравнивается, когда решают, та же ли это память (оценка на val)."""
        return self.kind, self.text


@dataclass(slots=True)
class Bullet(Note):
    """Пункт ACE: раздел плейбука и счётчики меток рефлектора."""
    section: str = ""
    helpful: int = 0
    harmful: int = 0


@dataclass(slots=True)
class Rule(Note):
    """Стратегическое правило SCOPE."""
    domain: str = ""
    rationale: str = ""
    confidence: float = 0.85


@dataclass(slots=True)
class Pair(Note):
    """Пара DC-RS: вопрос и решение (text)."""
    question: str = ""

    def head(self):
        return self.question

    def key(self):
        return self.kind, self.text, self.question


@dataclass(slots=True)
class Entry(Note):
    """Типизированная запись прототипа: условие применения и счётчики."""
    when: str = ""
    helpful: int = 0
    harmful: int = 0

    def head(self):
        return self.when or Note.head(self)

    def key(self):
        return self.kind, self.text, self.when


@dataclass(slots=True)
class Hook(Note):
    """Урок по ошибке инструмента: показывается, когда текст ошибки содержит trigger."""
    trigger: str = ""

    def head(self):
        return self.trigger


@dataclass(slots=True)
class Skill(Note):
    """Skill EvoLib: подзадача целиком; doc — её description, по нему ищутся похожие; ig — прирост задачи,
    fig — приросты попыток, где skill был в промпте (Future IG)."""
    doc: str = ""
    ig: float = 0.0
    fig: list = field(default_factory=list)


@dataclass(slots=True)
class Insight(Note):
    """Insight EvoLib «If ..., then ...»; fig — как у Skill."""
    fig: list = field(default_factory=list)


@dataclass(slots=True)
class Solution(Note):
    """Лучшее решение задачи (EvoLib): text — решение, score — его балл."""
    question: str = ""
    score: float = 0.0
    answer: str = ""


@dataclass(slots=True)
class Iteration(Note):
    """Итерация MCE: text — навык, точность на train и val, открытые записи памяти после итерации."""
    train: float = None
    val: float = None
    records: list = field(default_factory=list)


@dataclass(frozen=True)
class Kind:
    record: type = Note
    ops: tuple = ALL
    per: str = "run"           # run | task: записи вида стираются перед каждой задачей
    private: bool = False      # решатель не видит никогда
    apart: bool = False        # решатель видит только через блок, назвавший вид
    ids: str = "r"             # префикс id; у скрытых видов свой, чтобы не сдвигать нумерацию открытых


def perspectives(schema, names):
    """Виды «вид:перспектива» для каждой перспективы."""
    return {f"{kind}:{p}": spec for p in names for kind, spec in schema.items()}


def perspective_kind(base, perspective):
    return f"{base}:{perspective}" if perspective else base


def slug(name):
    return name.lower().strip().replace(" ", "_").replace("&", "and")

# память


@dataclass
class Memory:
    schema: dict = field(default_factory=lambda: {"note": Kind()})
    records: list = field(default_factory=list)     # записи всех видов в порядке появления
    counters: dict = field(default_factory=dict)

    def spec(self, kind):
        if kind not in self.schema:
            raise KeyError(f"в памяти нет вида {kind}; есть {', '.join(self.schema)}")
        return self.schema[kind]

    def ops(self, kind):
        return self.spec(kind).ops

    def allow(self, kind, op):
        if op not in self.ops(kind):
            raise Forbidden(f"{op} is not allowed for {kind} entries")

    def private(self, r):
        return self.spec(r.kind).private

    def visible(self):
        """Всё, что может увидеть решатель: открытые и отдельные виды."""
        return [r for r in self.records if not self.private(r)]

    def new_task(self):
        """Записи видов, живущих одну задачу, уходят без операции delete: это срок жизни, а не правка."""
        self.records = [r for r in self.records if self.spec(r.kind).per != "task"]

    def add(self, text, kind=None, **values):
        kind = kind or next(iter(self.schema))
        spec = self.spec(kind)
        self.allow(kind, "add")
        n = self.counters[spec.ids] = self.counters.get(spec.ids, 0) + 1
        rec = spec.record(f"{spec.ids}{n}", text, kind, **values)
        self.records.append(rec)
        return rec

    def edit(self, id, text=None, **values):
        """Новый текст или поля записи. Только условие применения (when) — операция narrow."""
        rec = self.get(id)
        if text is not None or set(values) - {"when"}:
            self.allow(rec.kind, "edit")
        elif values and "edit" not in self.ops(rec.kind):
            self.allow(rec.kind, "narrow")
        if text is not None:
            rec.text = text
        for k, v in values.items():
            setattr(rec, k, v)
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
        """Записи видов kinds; без видов — все открытые."""
        if kinds:
            return [r for r in self.records if r.kind in kinds]
        return [r for r in self.visible() if not self.spec(r.kind).apart]

    def text(self, *kinds):
        return "\n".join(f"[{r.id}] {r.text}" for r in self.of(*kinds))

    def chars(self):
        return sum(len(r.text) for r in self.visible())

    def key(self):
        return tuple(r.key() for r in self.visible())

    def opened(self):
        """Копия видимых решателю записей (снимок для отката)."""
        return copy.deepcopy(self.visible())

    def restore(self, records):
        """Видимые решателю записи заменяются копией records; скрытые остаются."""
        self.records = copy.deepcopy(records) + [r for r in self.records if self.private(r)]

    def save(self, path):
        json.dump([asdict(r) for r in self.records], open(path, "w"), ensure_ascii=False, indent=1)

# что блоки требуют от памяти


def needs(*names, kinds=()):
    """Пометка блока: записям видов kinds нужны поля names. kinds="*" — всем открытым видам;
    без kinds — хотя бы одному виду. Пустые names — только чтобы такие виды были."""
    def mark(block):
        block.needs = getattr(block, "needs", ()) + ((kinds if kinds == "*" else tuple(kinds), tuple(names)),)
        return block
    return mark


def requirements(*blocks):
    """Все пометки needs в блоках и в том, что они замкнули: обёртки (seq, each, ask, show) держат
    внутренние блоки в замыканиях."""
    out, seen, todo = [], set(), list(blocks)
    while todo:
        b = todo.pop()
        if id(b) in seen:
            continue
        seen.add(id(b))
        if isinstance(b, (tuple, list)):
            todo += b
        elif isinstance(b, dict):
            todo += b.values()
        elif callable(b) and not isinstance(b, type):
            out += getattr(b, "needs", ())
            for cell in getattr(b, "__closure__", None) or ():
                try:
                    todo.append(cell.cell_contents)
                except ValueError:
                    pass
            todo += getattr(b, "__defaults__", None) or ()
    return out


def check(schema, reqs):
    """Расхождения пометок со схемой, списком строк."""
    missing = lambda spec, names: [n for n in names if n not in {f.name for f in fields(spec.record)}]
    problems = []
    for kinds, names in reqs:
        if kinds == "*":
            kinds = tuple(k for k, s in schema.items() if not s.private and not s.apart)
        if not kinds:
            if all(missing(s, names) for s in schema.values()):
                problems.append(f"ни у одного вида нет полей {', '.join(names)}")
            continue
        for k in kinds:
            matched = {n: s for n, s in schema.items() if n == k or n.startswith(k + ":")}
            if not matched:
                problems.append(f"нет вида {k}")
            for n, s in matched.items():
                if missing(s, names):
                    problems.append(f"у записей {n} ({s.record.__name__}) нет полей {', '.join(missing(s, names))}")
    return list(dict.fromkeys(problems))
