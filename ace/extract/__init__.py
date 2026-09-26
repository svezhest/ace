"""Извлечение: что вынести из группы попыток вопроса. extractor(ex, group, memory) -> Extraction | None;
память читает только для полей промпта (что было показано, какие записи помечать).

Ядро есть всегда: текст уроков (lessons) и баллы попыток (scores). Добавки объявляются: извлечение — что
даёт (gives), память — что ей нужно (requires). Сборка ученика сравнивает два множества: это единственный
стык с проверкой. Имена добавок:

    labels        метки записей, бывших в попытке: Labels(helpful, harmful) (ACE)
    confidence    уверенность урока при рождении (SCOPE)
    domain        домен урока (SCOPE)
    attribution   какие записи были в промпте каких попыток (EvoLib, Future IG)
    ig            прирост лучшей попытки группы (EvoLib)
    best_answer   лучшее решение вопроса (EvoLib)
    operations    операции над библиотекой, предложенные по вопросу: словари operation / id / content (TF-GRPO)
    rationale     обоснование урока (SCOPE)
    trigger       фрагмент ошибки, по которому урок показывается (хуки по ошибкам)
    attempt       номер попытки, на которой урок извлечён (SCOPE: урок — в память перспективы попытки)
    input         вход задачи, как его видел решатель (DC: вопрос куратора)
    sheet         что стояло в [[CHEATSHEET]] у решателя (DC-RS хранит его как прошлый cheatsheet)

Масштаб извлечения (scale): "question" — extractor(ex, group, memory) после каждого вопроса; "batch" —
batch(ex, groups, memory) -> [Extraction] на батче, стадиями по всему батчу (TF-GRPO). Извлечение на шаге (SCOPE:
правило посреди попытки) — step(ex, attempt, шаг, memory) -> Extraction | None; у остальных его нет.
Реализации — extract/<метод>.py."""
from dataclasses import dataclass, field

LABELS = "labels"
CONFIDENCE = "confidence"
DOMAIN = "domain"
ATTRIBUTION = "attribution"
IG = "ig"
BEST_ANSWER = "best_answer"
OPERATIONS = "operations"
RATIONALE = "rationale"
TRIGGER = "trigger"
ATTEMPT = "attempt"
INPUT = "input"
SHEET = "sheet"


class Contract(ValueError):
    """Нарушен стык сборки (добавки памяти и извлечения): ошибка кода метода, прогон останавливается."""


@dataclass
class Labels:
    helpful: list = field(default_factory=list)
    harmful: list = field(default_factory=list)


@dataclass
class Extraction:
    group: object               # сырое: вопрос и попытки (DC и MCE память читает его)
    lessons: list               # ядро: текст уроков
    scores: list                # ядро: баллы попыток группы; пусто, если вердикта нет
    extras: dict = field(default_factory=dict)      # объявленные добавки: имя -> значение


class Extractor:
    gives = frozenset()
    scale = "question"
    steps = False               # извлекает и на шаге попытки (step)
    skilled = False             # подставляет навык меты (ex.skill) в свои промпты

    def __call__(self, ex, group, memory):
        raise NotImplementedError

    def batch(self, ex, groups, memory):
        raise NotImplementedError

    def step(self, ex, attempt, step, memory):
        return None


class Raw(Extractor):
    """Нет извлечения: память читает сырое (MCE)."""
    def __call__(self, ex, group, memory):
        return Extraction(group, [], scores(group))


class Seen(Raw):
    """Нет извлечения, но память видит, что показал решатель (DC: вход задачи и cheatsheet — Prompt.seen)."""
    gives = frozenset({INPUT, SHEET})

    def __call__(self, ex, group, memory):
        x = super().__call__(ex, group, memory)
        x.extras = {k: group.episodes[0].prompt.seen[k] for k in self.gives}
        return x


def scores(group):
    """1 / 0 по вердикту каждой попытки; пусто, если вердикта нет."""
    eps = group.episodes
    if any(e.ok is None for e in eps):
        return []
    return [float(bool(e.ok)) for e in eps]


def missing(memory, extractor):
    """Добавки, которые память требует, а извлечение не даёт."""
    return set(memory.requires) - set(extractor.gives if extractor else ())
