"""Ученик: метод, собранный из уровней (docs/architecture.md).

    попытки и в зачёт   attempts: Attempts(n, temperature(k), pick)             loop.py
    вердикт попытки     verdict: golden | yes_no | judge | none                 verdict.py
    вердикт группы      group_verdict: vote | none                              verdict.py
    извлечение          extract(ex, group, memory) -> Extraction; gives         extract/
    память              контейнер + learn(ex, extractions); requires            memory/
    показ               show.prompt -> Prompt, show.on_step -> Patch            show/
    когда учится        every (раз в сколько вопросов), flush (неполный батч в конце прохода)
    среда попытки       env: Env | Sandbox(per="call" | "attempt")              env/

Хуки: перед попыткой память узнаёт о новой попытке (begin: срок жизни «попытка»), показ даёт промпт; на шаге
при обучении извлечение может дать урок сразу (extract.step, SCOPE) — память принимает его тут же, затем показ
может вмешаться (Patch); извлечение — на конце вопроса (или стадиями на батче: scale="batch"), память
принимает извлечённое на батче. Обёртки
(ace/wrap/) перехватывают хуки поверх ученика.
Стык с проверкой один: память требует добавки (requires), извлечение их даёт (gives); сверка при сборке.
Абляция — swap(ученик, name, уровень=замена)."""
import copy
from dataclasses import dataclass, field, replace

from . import verdict as verdicts
from .env import Env
from .extract import missing
from .loop import Attempts
from .memory import Lessons
from .show import Show, Whole


@dataclass
class Learner:
    name: str
    memory: object = field(default_factory=Lessons)
    show: Show = field(default_factory=Whole)
    extract: object = None
    attempts: Attempts = field(default_factory=Attempts)
    verdict: callable = verdicts.golden
    group_verdict: callable = verdicts.none
    every: int = 1
    flush: bool = False
    epochs: int = 1             # проходов по train по умолчанию, как в апстриме
    env: Env = field(default_factory=Env)
    skill: str = ""             # навык от мета-уровня (MCE над учеником); сам ученик его не пишет
    pending: list = field(default_factory=list, init=False, repr=False)    # извлечённое до батча
    gated: list = field(default_factory=list, init=False, repr=False)      # решения Gate (в лог по вопросу)

    def __post_init__(self):
        lack = missing(self.memory, self.extract)
        if lack:
            raise ValueError(f"{self.name}: память требует от извлечения {', '.join(sorted(lack))}, а оно этого не даёт")

    # хуки масштабов

    def prompt(self, ex, item, k, memory=None):
        """Промпт попытки k; memory — показать другую версию памяти (новая попытка из извлечения)."""
        memory = self.memory if memory is None else memory
        memory.begin(k)
        p = self.show.prompt(ex, memory, item, k)
        p.temperature, p.top_p = self.attempts.temperature(k), self.attempts.top_p(k)
        return p

    def on_step(self, ex, attempt, step):
        if attempt.training and self.extract is not None:
            x = self.extract.step(ex, attempt, step, self.memory)
            if x:
                self.memory.learn(ex, [x])
        return self.show.on_step(ex, self.memory, attempt, step)

    def on_attempt(self, ex, episode):
        pass

    def on_question(self, ex, group):
        if self.extract is not None and self.extract.scale == "question":
            self.keep(self.extract(ex, group, self.memory))

    def keep(self, x):
        """Извлечённое — до батча; добавки только объявленные."""
        if x is None:
            return
        undeclared = set(x.extras) - set(self.extract.gives)
        if undeclared:
            raise ValueError(f"{self.name}: извлечение дало необъявленные добавки {', '.join(sorted(undeclared))}")
        self.pending.append(x)

    def on_batch(self, ex, groups):
        if self.extract is not None and self.extract.scale == "batch":
            for x in self.extract.batch(ex, groups, self.memory):
                self.keep(x)
        if self.pending:
            self.memory.learn(ex, self.pending)
        self.pending = []

    def on_pass(self, ex):
        self.pending = []           # неполный батч без flush отбрасывается

    # протокол и обёртки

    def watches_steps(self):
        return self.show.watches_steps

    def snapshot(self):
        """Версия памяти для отката (лучшая по val, Gate, Meta)."""
        return copy.deepcopy(self.memory)

    def restore(self, snapshot):
        self.memory = copy.deepcopy(snapshot)

    def key(self):
        """Ключ кэша val; при случайном показе его нет."""
        return None if self.show.random else self.memory.key()

    def dump(self):
        return self.memory.dump()


def swap(learner, name=None, **levels):
    """Ученик с заменёнными уровнями; проверка стыка идёт заново. Обёртка (ace/wrap/) меняет уровни своего
    ученика."""
    if not isinstance(learner, Learner):
        return learner.swap(name, **levels)
    return replace(learner, name=name or learner.name, **levels)
