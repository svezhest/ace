"""Цикл, один на все методы. Эксперимент — метод на задаче: проходы по вопросам задачи; вопрос — группа попыток;
попытка — шаги решателя. Хуки ученика по масштабам (шаг, попытка, вопрос, батч, проход) — docs/architecture.md.

На val и тесте (training = False) цикл зовёт только prompt и on_step. Сам цикл делает: среду попытки,
вердикты (верный ответ в эпизоде только при golden), выбор ответа в зачёт, запись прочитанного
инструментами (episode.used), протокол метода (Protocol: онлайн; офлайн с выбором лучшей по val версии) и лог."""
import copy
import json
import random
import time
import traceback
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from functools import partial
from pathlib import Path
from typing import Callable

from . import config, render
from .model import Call, Outcome, messages, params
from .tasks import accuracy, final_answer
from .extract import Contract
from .verdict import LABELED, majority


@dataclass
class Solver:
    """Решатель метода вместо общего (генератор ACE, DC): call(заметка) -> Call — запрос целиком, заметка рефлектора
    внутри него; answer(ответ текстом) -> ответ в зачёт; talk(модель, Call) -> Reply — свой разговор метода вместо
    одного вызова (DC: исполнение кода между вызовами)."""
    call: Callable
    answer: Callable
    talk: Callable = None


@dataclass
class Prompt:
    """Что ученик даёт попытке."""
    system: str = ""            # добавка к системному промпту решателя; роль задачи и подсказку среды ставит цикл
    tools: tuple = ()           # инструменты чтения памяти
    deps: object = None         # их fs.FS; прочитанное (deps.reads) цикл пишет в episode.used
    rounds: int = 0             # лишних шагов решателю на чтение
    shown: list = field(default_factory=list)   # id показанных записей
    temperature: float = 0
    note: str = ""              # заметка к сообщению решателю (раунды рефлексии ACE)
    solver: Solver = None       # свой решатель метода; тогда системного промпта задачи и среды нет
    seen: dict = field(default_factory=dict)    # что ещё показал решатель (DC: вход и cheatsheet) — для извлечения


@dataclass
class Attempt:
    """Идущая попытка: что видит on_step."""
    question: str
    k: int                      # номер попытки в группе
    training: bool
    prompt: Prompt
    system: str = ""            # системный промпт попытки целиком (Patch(system) пишет новый на его основе)
    steps: list = field(default_factory=list)       # model.Step до текущего включительно
    turns: list = field(default_factory=list)       # номер ответа модели у каждого шага (шаги одного ответа — вместе)
    patches: list = field(default_factory=list)     # model.Patch, применённые после шагов
    shown: list = field(default_factory=list)       # id записей, показанных посреди попытки (Patch)
    fired: list = field(default_factory=list)       # (id показанного урока, помог ли) — исходы показа после ошибки


@dataclass
class Episode:
    """Законченная попытка, как её видит обучение."""
    question: str
    k: int
    prompt: Prompt
    output: str                 # вся траектория текстом: ответы, вызовы инструментов, их результаты
    final: str                  # последний ответ модели
    answer: str
    steps: list = field(default_factory=list)
    truncated: bool = False
    used: list = field(default_factory=list)        # id записей, прочитанных инструментами показа
    fired: list = field(default_factory=list)
    patches: list = field(default_factory=list)
    ok: bool = None             # вердикт попытки; None — его нет
    target: str = ""            # верный ответ — только при golden
    system: str = ""            # системный промпт при запуске попытки (роль задачи, подсказка среды, показ)
    outcome: Outcome = Outcome.answer   # чем кончился вызов модели: ответ, кончились запросы, вывод не прошёл схему

    @property
    def shown(self):
        return self.prompt.shown


@dataclass
class Group:
    """Попытки одного вопроса."""
    question: str
    episodes: list
    target: str = ""            # верный ответ — только при golden
    vote: str = ""              # вердикт группы vote: самый частый ответ
    chosen: int = 0             # чья попытка в зачёт
    pick: str = "first"         # как она выбрана
    pass_at_k: bool = False     # выбрана по метке: зачёт — pass@k, а не точность
    item: dict = None           # вопрос как в выборке (у MCE — с id выборки)
    i: int = None               # номер вопроса в проходе

    @property
    def answer(self):
        return self.episodes[self.chosen].answer

# что в зачёт: pick(group, check) -> номер попытки; check(ответ) — проверка задачи


def first(group, check):
    return 0


def vote(group, check):
    """Ответ большинства (self-consistency); при равенстве первый встреченный."""
    top = majority(e.answer for e in group.episodes)
    if not top:
        return 0
    return next(i for i, e in enumerate(group.episodes) if e.answer == top)


def best(group, check):
    """Первая верная по метке, иначе первая (SCOPE K=2). Это pass@k — помечается в логе."""
    return next((i for i, e in enumerate(group.episodes) if check(e.answer)), 0)

# температура попытки k


SPREAD = 0.7                # попытки после первой (self-consistency, группа контраста)


def greedy(k):
    return 0


def spread(k):
    """Первая попытка жадная, остальные при SPREAD."""
    return 0 if k == 0 else SPREAD


@dataclass
class Attempts:
    """Сколько попыток на вопрос и что в зачёт. Различие попыток: температура попытки k; выборка показа и
    разделённая память — в prompt(ex, item, k) ученика; заметка рефлектора — ex.retry из извлечения."""
    n: int = 1
    temperature: Callable = greedy
    pick: Callable = first

    def count(self, training):
        """Попыток на вопрос: при обучении вся группа; на val и тесте — сколько нужно выбору в зачёт (first — одна:
        остальные попытки нужны только обучению, TF-GRPO оценивает итогового агента)."""
        return self.n if training or self.pick is not first else 1


@dataclass(frozen=True)
class Protocol:
    """Протокол метода — как у его апстрима: на чём память учится и что идёт в зачёт.
    offline   обучение на train, после каждого прохода val; тест на потоке с лучшей по val версией памяти
    epochs    проходов обучения (не больше: пустая выборка ученика кончает обучение раньше — бюджет вызовов
              GEPA); онлайн — по тестовому потоку, в зачёт последний
    window    онлайн: тест окна — перед обучением на каждых window вопросах они решаются текущей памятью без
              обучения, это и в зачёт (ACE online); 0 — в зачёт первая попытка обучения
    recheck   после обучения на вопросе — попытка новой памятью, только в лог (ACE post_train)
    final     офлайн без val: проход по train только учит, в зачёт — тест памятью после обучения (TF-GRPO)"""
    offline: bool = False
    epochs: int = 1
    window: int = 0
    recheck: bool = False
    final: bool = False

    @property
    def val(self):
        return self.offline and not self.final

    @property
    def name(self):
        if self.final:
            kind = "final"
        elif self.offline:
            kind = "offline"
        else:
            kind = "online"
        window = f"-w{self.window}" if self.window else ""
        return f"{kind}{window}-e{self.epochs}"

    def check(self, name, verdict=None, split=""):
        """Ошибка сборки: несовместимые части. С вердиктом — ошибка запуска при утечке метки: онлайн с несколькими
        проходами по тестовому потоку, а вердикт попытки видит метку (память выучит ответы тех же вопросов, в зачёт —
        последний проход). Поток train (split) — не тест."""
        if self.final and not self.offline:
            raise ValueError(f"{name}: протокол final — только офлайн")
        if self.window and self.offline:
            raise ValueError(f"{name}: тест окна — только онлайн")
        if not self.offline and self.epochs > 1 and verdict in LABELED and split != "train":
            raise ValueError(f"{name}: онлайн с {self.epochs} проходами по тестовому потоку при вердикте, который "
                             "видит метку, — утечка ответов; нужен офлайн")


class Experiment:
    """Метод × задача. Хукам ученика — как ex: модель, задача, флаг обучения, номер прохода, батча и вопроса и
    число вопросов, навык меты (skill), evaluate() и retry()."""
    def __init__(self, task, learner, model):
        self.task = task
        self.learner = learner
        self.model = model
        self.training = True
        self.epoch = 0          # номер прохода
        self.batch = 0          # номер батча в проходе
        self.i = 0              # номер вопроса в проходе
        self.total = 0          # вопросов в проходе
        self.item = None        # текущий вопрос
        self.skill = ""         # навык от мета-уровня (MCE): уровни ученика подставляют его в промпты обучения
        self.retried = []       # попытки из извлечения (retry) на текущем вопросе — в лог по вопросу
        self.scores = {}        # кэш val по ключу памяти

    @contextmanager
    def frozen(self):
        """Без обучения: val, тест, новая попытка из извлечения; флаг обучения потом прежний."""
        training = self.training
        self.training = False
        try:
            yield
        finally:
            self.training = training

    def attempt(self, item, k, prompt):
        if prompt.solver is not None:
            return self.attempt_by_solver(item, k, prompt)
        env = self.learner.env.open()
        try:
            running = Attempt(item["question"], k, self.training, prompt, self.task.system + env.hint + prompt.system)
            tools = env.tools + prompt.tools
            watch = self.stepper(running) if tools and self.learner.watches_steps else None
            user = render.user_message(self.task.instr, item["question"], prompt.note)
            call = Call(messages(user, running.system), params(prompt.temperature), tools=tools, deps=prompt.deps,
                        rounds=env.rounds + prompt.rounds, on_step=watch)
            reply = self.model.ask(call)
        finally:
            env.close()
        final = reply.output or ""
        used = list(prompt.deps.reads) if prompt.deps is not None else []
        ep = Episode(running.question, k, prompt, output=reply.text, final=final, answer=final_answer(final),
                     steps=reply.steps, truncated=reply.truncated, used=used, fired=running.fired,
                     patches=running.patches, system=running.system, outcome=reply.outcome)
        self.learner.verdict(self, ep, item["target"])
        return ep

    def attempt_by_solver(self, item, k, prompt):
        """Попытка своим решателем метода: без инструментов, один вызов или разговор метода."""
        solver = prompt.solver
        call = solver.call(prompt.note)
        if solver.talk:
            reply = solver.talk(self.model, call)
        else:
            reply = self.model.ask(call)
        final = reply.output or ""
        ep = Episode(item["question"], k, prompt, output=reply.text, final=final, answer=solver.answer(final),
                     truncated=reply.truncated, outcome=reply.outcome)
        self.learner.verdict(self, ep, item["target"])
        return ep

    def stepper(self, running):
        """on_step для модели: каждый новый шаг — ученику; его Patch-и одного запроса сливаются."""
        def on_step(new):
            turn = running.turns[-1] + 1 if running.turns else 0
            patch = None
            for step in new:
                running.steps.append(step)
                running.turns.append(turn)
                mine = self.learner.on_step(self, running, step)
                if mine:
                    running.patches.append(mine)
                    patch = combine(patch, mine)
            return patch
        return on_step

    def question(self, item):
        """Группа попыток одного вопроса; при обучении — события попытки (on_attempt). Обучение на вопросе
        (on_question) зовёт цикл после ответа: его ошибка не меняет ответ."""
        learner = self.learner
        eps = []
        for k in range(learner.attempts.count(self.training)):
            ep = self.attempt(item, k, learner.prompt(self, item, k))
            eps.append(ep)
            if self.training:
                learner.on_attempt(self, ep)
        group = Group(item["question"], eps, target=eps[0].target, item=item, i=self.i)
        learner.group_verdict(self, group)
        pick = learner.attempts.pick
        group.pick = pick.__name__
        group.pass_at_k = pick is best
        group.chosen = pick(group, lambda answer: self.task.check(answer, item["target"]))
        return group

    def retry(self, memory, note):
        """Новая попытка текущего вопроса с показом из memory и заметкой — стрелка извлечение -> попытки
        (раунды рефлексии ACE). На её шагах не учатся."""
        prompt = self.learner.prompt(self, self.item, 0, memory)
        prompt.note = note
        with self.frozen():
            ep = self.attempt(self.item, 0, prompt)
        self.retried.append(ep)
        return ep

    def evaluate(self):
        """(верно, обрыв) по вопросам val без обучения. Одна и та же память не считается дважды; при случайном
        показе ключа нет и кэша тоже."""
        key = self.learner.key()
        if key is not None and key in self.scores:
            return self.scores[key]
        i, item = self.i, self.item
        out = []
        try:
            with self.frozen():
                for n, row in enumerate(self.task.load("val")):
                    self.i, self.item = n, row
                    out.append(self.result(self.question(row), row))
        finally:
            self.i, self.item = i, item
        if key is not None:
            self.scores[key] = out
        return out

    def result(self, group, item):
        return self.task.check(group.answer, item["target"]), group.episodes[group.chosen].truncated


def combine(patch, mine):
    """Два Patch одного шага (или None) в один."""
    if patch is None:
        return mine
    if mine is None:
        return patch
    return patch.merge(mine)


def best_index(values):
    """Номер лучшего по val: строго больше, при равенстве ранний (выбор версии офлайн, _find_best_iteration MCE)."""
    best, top = None, float("-inf")
    for i, v in enumerate(values):
        if v > top:
            best, top = i, v
    return best


def finish(ep):
    """Чем кончилась попытка: length — обрыв по длине, rounds — запросы кончились без ответа, broken — вывод так и не
    прошёл схему, stop — ответ."""
    if ep.truncated:
        return "length"
    return {Outcome.step: "rounds", Outcome.broken: "broken"}.get(ep.outcome, "stop")


def in_score(row, last_epoch):
    """Запись лога в зачёт: тест или онлайн-проход last_epoch (старые логи — без phase и epoch)."""
    phase = row.get("phase", "online")
    return phase == "test" or (phase == "online" and row.get("epoch", 0) == last_epoch)


def attempt_entry(ep):
    return dict(k=ep.k, answer=ep.answer, ok=ep.ok, temperature=ep.prompt.temperature, finish=finish(ep),
                shown=ep.shown, read=ep.used, fired=ep.fired, patches=[asdict(p) for p in ep.patches])


def retry_entry(ep):
    return dict(answer=ep.answer, ok=ep.ok, finish=finish(ep), note=ep.prompt.note, output=ep.output)


def entry(phase, epoch, i, group, item, correct, gated, memory_chars, sec, retried=()):
    """Запись лога по вопросу: ответ в зачёт, как выбран, вся группа и попытки из извлечения (раунды ACE)."""
    chosen = group.episodes[group.chosen]
    return dict(phase=phase, epoch=epoch, i=i, question=group.question, target=item["target"], answer=group.answer,
                correct=correct, pick=group.pick, pass_at_k=group.pass_at_k, vote=group.vote, finish=finish(chosen),
                output=chosen.output, shown=chosen.shown, read=chosen.used, gated=gated, memory_chars=memory_chars,
                sec=sec, group=[attempt_entry(e) for e in group.episodes], retries=[retry_entry(e) for e in retried])


def failed(phase, epoch, i, item, error):
    """Запись лога о вопросе (или событии прохода), на котором прогон упал: неверно, с текстом ошибки."""
    return dict(phase=phase, epoch=epoch, i=i, question=item["question"] if item else "",
                target=item["target"] if item else "", answer="", correct=False, finish="error",
                error="".join(traceback.format_exception(error)), group=[])


def folder(task, n, learner, model):
    """Папка результатов: задача и размер, метод, протокол, модель и бэкенд — прогоны разных настроек не затирают
    друг друга."""
    parts = (learner.protocol.name, model.name, getattr(model, "backend", ""))
    tag = "_".join(x for x in parts if x)
    return Path(config.RESULTS) / f"{task.name}{n}" / learner.name / tag


def run(task, learner, model, n=config.SIZE, out=None, split=""):
    """Прогон метода на задаче по протоколу ученика (learner.protocol).
        онлайн    поток split, память учится по ходу, epochs проходов, в зачёт последний: первая попытка обучения,
                  а с window — тест окна; до первого прохода — начальный тест всего потока (в лог)
        офлайн    обучение на train, после каждого прохода val; тест на split с лучшей по val версией памяти (строго
                  больше, при равенстве ранняя), без обучения
        final     офлайн без val: тест памятью после последнего прохода, как итоговый агент апстрима
        recheck   после обучения на вопросе ещё попытка новой памятью, только в лог
    Лог и итог пишутся после каждого вопроса, память — в конце. Исключение на вопросе (или в событии прохода)
    уходит в лог записью finish="error", вопрос засчитывается неверным, прогон идёт дальше; в итоге — errors.
    Исключение обучения — своя запись (phase learn), ответ вопроса в зачёте остаётся. Нарушение стыка сборки
    (Contract) прогон останавливает."""
    random.seed(config.SEED)
    learner = copy.deepcopy(learner)        # в реестре память ученика пуста: каждый прогон с чистой
    proto = learner.protocol
    proto.check(learner.name, learner.verdict, split)
    parts = []
    if proto.offline:
        parts.append("train")
    if proto.val or learner.needs_val:
        parts.append("val")
    for part in parts:
        try:
            task.load(part)
        except (FileNotFoundError, ValueError) as error:
            raise ValueError(f"{learner.name}: протоколу {proto.name} нужна выборка {part} задачи {task.name} — "
                             f"{error}")
    return Run(task, learner, model, n, out, split).everything()


class Run:
    """Один прогон: эксперимент, лог по вопросам и версии памяти после проходов (офлайн)."""
    def __init__(self, task, learner, model, n, out, split):
        self.task = task
        self.learner = learner
        self.model = model
        self.n = n
        self.out = out
        self.split = split
        self.proto = learner.protocol
        self.ex = Experiment(task, learner, model)
        self.log = []
        self.versions = []      # (верных на val, версия памяти) после каждого прохода

    def everything(self):
        done = False
        try:
            if self.proto.window:
                self.initial_test()
            for epoch in range(self.proto.epochs):
                if not self.train_pass(epoch):
                    break
            if self.proto.offline:
                self.final_test()
            done = True
        finally:
            self.save(done, last=True)          # прерванный прогон (Ctrl-C) — done=False, память на момент обрыва
        return self.summary(True)

    def initial_test(self):
        for i, item in enumerate(self.task.load(self.split, self.n)):
            self.test("initial", i, item)

    def train_pass(self, epoch):
        """Проход обучения; вопросов нет (ученик исчерпал бюджет, GEPA) — прохода нет и обучение кончено: False."""
        ex = self.ex
        learner = self.learner
        proto = self.proto
        items = learner.sample(ex, "train" if proto.offline else self.split, self.n)
        if not items:
            return False
        ex.epoch = epoch
        ex.total = len(items)
        ex.batch = 0
        batch = []
        self.guarded("pass", 0, None, partial(learner.on_pass_start, ex))
        phase = "train" if proto.offline or proto.window else "online"
        every = learner.every
        for i, item in enumerate(items):
            if proto.window and i % proto.window == 0:
                for j in range(i, min(i + proto.window, len(items))):
                    self.test("online", j, items[j])
            if i % every == 0:
                ex.batch = i // every
                ex.i, ex.item = i, item
                self.guarded("learn", i, item, partial(learner.on_batch_start, ex))
            self.train(phase, i, item, batch, closes=i % every == every - 1)
            if proto.recheck:
                self.test("post", i, item)
        if batch and learner.flush:
            self.guarded("learn", len(items) - 1, None, partial(learner.on_batch, ex, list(batch)))
        self.guarded("pass", len(items), None, partial(self.end_pass, epoch))
        return True

    def final_test(self):
        """Тест с лучшей по val версией памяти (без val — с последней)."""
        if self.versions:
            best = best_index([score for score, _ in self.versions])
            self.learner.restore(self.versions[best][1])
        self.ex.training = False
        self.ex.epoch = 0
        for i, item in enumerate(self.task.load(self.split, self.n)):
            self.test("test", i, item)

    def train(self, phase, i, item, batch, closes):
        """Вопрос обучения: ответ, обучение на вопросе, на последнем номере батча — обучение на батче (closes). Ответ
        идёт в лог после обучения (с решениями Gate и попытками извлечения); исключение обучения — своя запись
        (phase learn), ответ и его вердикт оно не меняет. Батч — вопросы с номерами батча: упавший до ответа в него
        не входит, соседние батчи от этого не сдвигаются; батч, где не решился ни один, не учит."""
        ex, learner = self.ex, self.learner
        t0 = time.time()
        gates = len(learner.gated)
        ex.retried = []
        ex.i, ex.item = i, item
        group = self.guarded(phase, i, item, partial(ex.question, item))
        if group is not None:
            batch.append(group)
            self.guarded("learn", i, item, partial(learner.on_question, ex, group))
        if closes:
            if batch:
                self.guarded("learn", i, item, partial(learner.on_batch, ex, list(batch)))
            batch.clear()
        if group is not None:
            self.record(phase, i, group, item, t0, gated=learner.gated[gates:], retried=ex.retried)

    def end_pass(self, epoch):
        learner = self.learner
        learner.on_pass(self.ex)
        if self.proto.val:
            score = sum(correct for correct, _ in self.ex.evaluate())
            print(f"val after epoch {epoch}: {score}", flush=True)
            self.versions.append((score, learner.snapshot()))

    def test(self, phase, i, item):
        self.guarded(phase, i, item, partial(self.tested, phase, i, item))

    def tested(self, phase, i, item):
        """Вопрос без обучения, в лог."""
        t0 = time.time()
        self.ex.i, self.ex.item = i, item
        with self.ex.frozen():
            group = self.ex.question(item)
        self.record(phase, i, group, item, t0)

    def guarded(self, phase, i, item, step):
        """step() — вопрос, обучение или событие прохода; исключение — в лог, прогон дальше. -> что вернул step
        (None при исключении)."""
        out = None
        try:
            out = step()
        except Contract:
            raise
        except Exception as error:
            self.log.append(failed(phase, self.ex.epoch, i, item, error))
            print(f"{self.task.name} {self.learner.name} {phase}{self.ex.epoch} {i:3} ОШИБКА {error!r}", flush=True)
        self.save()
        return out

    def record(self, phase, i, group, item, t0, gated=(), retried=()):
        epoch = self.ex.epoch
        correct = self.task.check(group.answer, item["target"])
        chars = self.learner.memory.chars()
        self.log.append(entry(phase, epoch, i, group, item, correct, gated=list(gated), memory_chars=chars,
                              sec=round(time.time() - t0, 1), retried=retried))
        done = [r for r in self.log if r["phase"] == phase and r["epoch"] == epoch]
        right = sum(r["correct"] for r in done)
        mark = "+" if correct else "-"
        print(f"{self.task.name} {self.learner.name} {phase}{epoch} {i:3} {mark} {right}/{len(done)} mem={chars}",
              flush=True)

    def summary(self, done):
        proto, model = self.proto, self.model
        final = [r for r in self.log if in_score(r, proto.epochs - 1)]
        answers = [r["answer"] for r in final]
        targets = [r["target"] for r in final]
        return dict(task=self.task.name, method=self.learner.name, model=model.name,
                    backend=getattr(model, "backend", ""), n=len(final), protocol=proto.name, epochs=proto.epochs,
                    offline=proto.offline, done=done, errors=sum(r["finish"] == "error" for r in self.log),
                    correct=sum(r["correct"] for r in final), truncated=sum(r["finish"] == "length" for r in final),
                    accuracy=accuracy(self.task, answers, targets), **model.usage())

    def save(self, done=False, last=False):
        if not self.out:
            return
        out = Path(self.out)
        out.mkdir(parents=True, exist_ok=True)
        (out / "log.json").write_text(json.dumps(self.log, ensure_ascii=False, indent=1))
        (out / "summary.json").write_text(json.dumps(self.summary(done), indent=1))
        if last:
            (out / "memory.json").write_text(json.dumps(self.learner.dump(), ensure_ascii=False, indent=1))
