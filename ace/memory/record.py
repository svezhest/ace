"""Запись памяти: id и неизменяемый текст. Правка текста — новая запись со своей статистикой.
Запись сама отдаёт краткую строку (head) и сериализуется (dump)."""
from dataclasses import asdict, dataclass, field

HEAD_CHARS = 80             # длина краткой строки записи (каталог, ls)
HELPFUL, HARMFUL = "helpful", "harmful"


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
    """Урок со статистикой: журнал исходов (метка на каждое событие), счётчики — его свёртки.
    Журнал ведёт система; текст урока не меняется никогда."""
    outcomes: list = field(default_factory=list)

    @property
    def helpful(self):
        return self.outcomes.count(HELPFUL)

    @property
    def harmful(self):
        return self.outcomes.count(HARMFUL)

    def dump(self):
        return dict(asdict(self), helpful=self.helpful, harmful=self.harmful)
