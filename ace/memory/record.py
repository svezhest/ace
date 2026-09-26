"""Запись памяти: id и неизменяемый текст. Правка текста — новая запись со своей статистикой.
Запись сама отдаёт краткую строку (head) и сериализуется (dump). Счётчики ACE — counters.py. Здесь же общее у
памяти обоих миров (Memory)."""
from dataclasses import asdict, dataclass, field

HEAD_CHARS = 80             # длина краткой строки записи (каталог, ls)


class Memory:
    """Общее у памяти обоих миров: records(), chars(), key(), dump(), learn(ex, extractions) — у каждой свои;
    requires — добавки, которые память требует от извлечения (extract/__init__.py); begin(k) — начало попытки k
    (здесь уходят записи со сроком жизни «попытка», tactical SCOPE)."""
    requires = frozenset()
    skilled = False             # подставляет навык меты (ex.skill) в свои промпты обучения
    placed = False              # живёт там, куда её ставит обёртка (at: папка под-итерации MCE)

    def begin(self, k):
        pass


@dataclass(frozen=True, eq=False)
class Record:
    id: str
    text: str

    def head(self):
        """Краткая строка: каталог, ls."""
        return self.text.splitlines()[0][:HEAD_CHARS] if self.text else ""

    def dump(self):
        return asdict(self)


@dataclass(frozen=True, eq=False)
class Lesson(Record):
    """Урок со статистикой: журнал исходов (метка на каждое событие) ведёт система, свёртки журнала — у метода
    (счётчики ACE — counters.Counted, Future IG — memory/evolib.py). Текст урока не меняется никогда."""
    outcomes: list = field(default_factory=list)
