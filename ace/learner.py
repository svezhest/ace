"""Ученик: метод, собранный из уровней (docs/architecture.md).

    попытки и в зачёт   attempts: Attempts(n, temperature(k), pick)             loop.py
    вердикт попытки     verdict: golden | yes_no | judge | none                 verdict.py
    вердикт группы      group_verdict: vote | none                              verdict.py
    извлечение          extract(ex, group, memory) -> Extraction; gives         extract/
    память              контейнер + learn(ex, extractions); requires            memory/
    решатель            solver: None — общий (показ, среда, шаги); свой решатель метода   solver/
    показ               show.prompt -> Prompt, show.on_step -> Patch; только у общего решателя   show/
    когда учится        every (раз в сколько вопросов), flush (неполный батч в конце прохода)
    протокол            protocol: Protocol(offline, epochs, window, recheck, final) — по апстриму метода  loop.py
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
from .extract import Contract, missing
from .loop import Attempts, Protocol, at_zero, default
from .memory import Lessons
from .show import Show, Whole

WHOLE = Whole()


@dataclass
class Learner:
    name: str
    memory: object = field(default_factory=Lessons)
    solver: object = None       # свой решатель метода (solver/); None — общий
    show: Show = None           # показ общего решателя; None — Whole()
    extract: object = None
    attempts: Attempts = field(default_factory=Attempts)
    verdict: callable = verdicts.golden
    group_verdict: callable = verdicts.none
    every: int = 1
    flush: bool = False
    protocol: Protocol = Protocol()
    env: Env = field(default_factory=Env)
    needs_val = False           # val нужен и без офлайна (Gate)
    pending: list = field(default_factory=list, init=False, repr=False)    # извлечённое до батча
    gated: list = field(default_factory=list, init=False, repr=False)      # решения Gate (в лог по вопросу)

    def __post_init__(self):
        self.protocol.check(self.name)
        self.check_solver()
        self.check_reads()
        lack = missing(self.memory, self.extract)
        if lack:
            raise Contract(f"{self.name}: память требует от извлечения {', '.join(sorted(lack))}, а оно этого не даёт")

    def check_reads(self):
        """Показ (или свой решатель) читает у памяти то, что объявил (reads): иначе он упадёт на первой попытке."""
        viewer = self.solver or self.viewer()
        lack = [a for a in viewer.reads if not hasattr(self.memory, a)]
        if lack:
            raise Contract(f"{self.name}: {'решатель' if self.solver else 'показ'} читает у памяти {', '.join(lack)}, "
                           "а у неё этого нет")

    def check_solver(self):
        """Свой решатель сам показывает память и ставит параметры вызова: уровни, которые при нём не действуют, —
        ошибка сборки, а не молча выключенная ступень абляции."""
        if self.solver is None:
            return
        dead = [name for name, on in (
            ("показ", self.show is not None),
            ("температура и top_p попыток", self.attempts.temperature is not at_zero or self.attempts.top_p is not default),
            ("среда", bool(self.env.tools or self.env.hint)),
            ("извлечение на шаге", self.extract is not None and self.extract.steps)) if on]
        if dead:
            raise ValueError(f"{self.name}: при своём решателе метода не действуют: {', '.join(dead)} "
                             "(меняются параметры решателя)")

    def viewer(self):
        return self.show or WHOLE

    # хуки масштабов

    def prompt(self, ex, item, k, memory=None):
        """Промпт попытки k; memory — показать другую версию памяти (новая попытка из извлечения)."""
        memory = self.memory if memory is None else memory
        memory.begin(k)
        if self.solver is not None:
            return self.solver.prompt(ex, memory, item, k)
        p = self.viewer().prompt(ex, memory, item, k)
        p.temperature, p.top_p = self.attempts.temperature(k), self.attempts.top_p(k)
        return p

    def sample(self, ex, split, n):
        """Вопросы прохода: первые n (MCE апстрима — случайная выборка на каждой итерации, wrap/mce.py)."""
        return ex.task.load(split, n)

    def on_pass_start(self, ex):
        pass

    def on_batch_start(self, ex):
        pass

    def on_step(self, ex, attempt, step):
        if attempt.training and self.extract is not None:
            x = self.extract.step(ex, attempt, step, self.memory)
            if x:
                self.memory.learn(ex, [x])
        return self.viewer().on_step(ex, self.memory, attempt, step)

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
            raise Contract(f"{self.name}: извлечение дало необъявленные добавки {', '.join(sorted(undeclared))}")
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
        return self.solver is None and self.viewer().watches_steps

    def snapshot(self):
        """Версия памяти для отката (лучшая по val, Gate, Meta)."""
        return copy.deepcopy(self.memory)

    def restore(self, snapshot):
        self.memory = copy.deepcopy(snapshot)

    def key(self):
        """Ключ кэша val; при случайном показе его нет."""
        return None if (self.solver or self.viewer()).random else self.memory.key()

    def dump(self):
        return self.memory.dump()


def swap(learner, name=None, **levels):
    """Ученик с заменёнными уровнями; проверка стыка идёт заново. Обёртка (ace/wrap/) меняет уровни своего
    ученика."""
    if not isinstance(learner, Learner):
        return learner.swap(name, **levels)
    return replace(learner, name=name or learner.name, **levels)
