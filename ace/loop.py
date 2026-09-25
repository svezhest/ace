"""Цикл, один на все методы. Эксперимент — проходы по задачам; вопрос — группа попыток; попытка — шаги
решателя. Ученик (learner.py) даёт промпт попытки и отвечает на события своих масштабов:

    шаг       on_step(ex, attempt, step) -> Patch | None     при обучении и на val / тесте
    попытка   prompt(ex, item, k) -> Prompt до, on_attempt(ex, episode) после
    вопрос    on_question(ex, group)                        группа есть всегда, обычно из одной попытки
    батч      on_batch_start(ex) перед первым вопросом батча (ex.batch — его номер в проходе); on_batch(ex, groups)
              раз в learner.every вопросов; неполный в конце прохода — если learner.flush
    проход    on_pass_start(ex) после выборки вопросов прохода; on_pass(ex) в конце; ex.evaluate() — точность на val

На val и тесте (training = False) цикл зовёт только prompt и on_step. Сам цикл делает: среду попытки,
вердикты (верный ответ в эпизоде только при golden), выбор ответа в зачёт, запись прочитанного
инструментами (episode.used), протокол метода (Protocol: онлайн; офлайн с выбором лучшей по val версии) и лог."""
import copy
import json
import random
import time
import traceback
from dataclasses import asdict, dataclass, field
from pathlib import Path

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
    call: callable
    answer: callable
    talk: callable = None


@dataclass
class Prompt:
    """Что ученик даёт попытке."""
    system: str = ""            # добавка к системному промпту решателя; роль задачи и подсказку среды ставит цикл
    tools: tuple = ()           # инструменты чтения памяти
    deps: object = None         # их fs.FS; прочитанное (deps.reads) цикл пишет в episode.used
    rounds: int = 0             # лишних шагов решателю на чтение
    shown: list = field(default_factory=list)   # id показанных записей
    temperature: float = 0
    top_p: float = None         # None — по умолчанию сервера (TF-GRPO: итоговый агент апстрима с top_p 0.95)
    note: str = ""              # заметка к сообщению решателю (раунды рефлексии ACE)
    solver: Solver = None       # свой решатель метода; тогда системного промпта задачи и среды нет


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
    steps: list
    truncated: bool
    used: list                  # id записей, прочитанных инструментами показа
    fired: list
    patches: list
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

    @property
    def answer(self):
        return self.episodes[self.chosen].answer

# что в зачёт: pick(group, check) -> номер попытки; check(ответ) — проверка задачи


def first(group, check):
    return 0


def vote(group, check):
    """Ответ большинства (self-consistency); при равенстве первый встреченный."""
    top = majority(e.answer for e in group.episodes)
    return next((i for i, e in enumerate(group.episodes) if top and e.answer == top), 0)


def best(group, check):
    """Первая верная по метке, иначе первая (SCOPE K=2). Это pass@k — помечается в логе."""
    group.pass_at_k = True
    return next((i for i, e in enumerate(group.episodes) if check(e.answer)), 0)


def at_zero(k):
    return 0


def default(k):
    """Настройка по умолчанию сервера (top_p)."""
    return None


@dataclass
class Attempts:
    """Сколько попыток на вопрос и что в зачёт. Различие попыток: температура и top_p попытки k; выборка
    показа и разделённая память — в prompt(ex, item, k) ученика; заметка рефлектора — ex.retry из извлечения."""
    n: int = 1
    temperature: callable = at_zero
    top_p: callable = default
    pick: callable = first

    def count(self, training):
        """Попыток на вопрос: при обучении вся группа; на val и тесте — сколько нужно выбору в зачёт (first — одна:
        остальные попытки нужны только обучению, TF-GRPO оценивает итогового агента)."""
        return self.n if training or self.pick is not first else 1


@dataclass(frozen=True)
class Protocol:
    """Протокол метода — как у его апстрима: на чём память учится и что идёт в зачёт.
    offline   обучение на train, после каждого прохода val; тест на потоке с лучшей по val версией памяти
    epochs    проходов обучения; онлайн — по тестовому потоку, в зачёт последний
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
        kind = "final" if self.final else "offline" if self.offline else "online"
        return f"{kind}{f'-w{self.window}' if self.window else ''}-e{self.epochs}"

    def check(self, name, verdict=None, split=""):
        """Ошибка сборки: несовместимые части. С вердиктом — ошибка запуска при утечке метки: онлайн с несколькими
        проходами по тестовому потоку, а вердикт попытки видит метку (память выучит ответы тех же вопросов, в зачёт —
        последний проход). Поток train (split) — не тест."""
        if self.final and not self.offline:
            raise ValueError(f"{name}: протокол final — только офлайн")
        if self.window and self.offline:
            raise ValueError(f"{name}: тест окна — только онлайн")
        if not self.offline and self.epochs > 1 and verdict in LABELED and split != "train":
            raise ValueError(f"{name}: онлайн с {self.epochs} проходами по тестовому потоку при вердикте, который видит "
                             "метку, — утечка ответов; нужен офлайн")


class Experiment:
    """Метод × задача. Хукам ученика — как ex: модель, задача, флаг обучения, номер прохода, батча и вопроса и
    число вопросов, навык меты (skill), evaluate() и retry()."""
    def __init__(self, task, learner, model):
        self.task, self.learner, self.model = task, learner, model
        self.training, self.epoch, self.batch, self.i, self.total, self.item = True, 0, 0, 0, 0, None
        self.skill = ""         # навык от мета-уровня (MCE): уровни ученика подставляют его в промпты обучения
        self.retried = []       # попытки из извлечения (retry) на текущем вопросе — в лог по вопросу
        self.scores = {}        # кэш val по ключу памяти

    def attempt(self, item, k, prompt):
        if prompt.solver is not None:
            return self.solved(item, k, prompt)
        env = self.learner.env.open()
        a = Attempt(item["context"], k, self.training, prompt, self.task.system + env.hint + prompt.system)
        try:
            tools = env.tools + prompt.tools
            reply = self.model.ask(Call(messages(render.user_message(self.task.instr, item["context"], prompt.note), a.system),
                                        params(prompt.temperature, prompt.top_p), tools=tools, deps=prompt.deps,
                                        rounds=env.rounds + prompt.rounds,
                                        on_step=self.stepper(a) if tools and self.learner.watches_steps() else None))
        finally:
            env.close()
        final = reply.output or ""
        ep = Episode(a.question, k, prompt, reply.text, final, final_answer(final), reply.steps, reply.truncated,
                     list(prompt.deps.reads) if prompt.deps is not None else [], a.fired, a.patches, system=a.system,
                     outcome=reply.outcome)
        self.learner.verdict(self, ep, item["target"])
        return ep

    def solved(self, item, k, prompt):
        """Попытка своим решателем метода: без инструментов, один вызов или разговор метода."""
        solver = prompt.solver
        call = solver.call(prompt.note)
        reply = solver.talk(self.model, call) if solver.talk else self.model.ask(call)
        final = reply.output or ""
        ep = Episode(item["context"], k, prompt, reply.text, final, solver.answer(final), [], reply.truncated,
                     [], [], [], outcome=reply.outcome)
        self.learner.verdict(self, ep, item["target"])
        return ep

    def stepper(self, a):
        """on_step для модели: каждый новый шаг — ученику; его Patch-и одного запроса сливаются."""
        def on_step(new):
            patch, turn = None, (a.turns[-1] + 1 if a.turns else 0)
            for step in new:
                a.steps.append(step)
                a.turns.append(turn)
                p = self.learner.on_step(self, a, step)
                if p:
                    a.patches.append(p)
                    patch = p if patch is None else patch.merge(p)
            return patch
        return on_step

    def question(self, item):
        """Группа попыток одного вопроса; при обучении — события попытки и вопроса."""
        learner, eps = self.learner, []
        for k in range(learner.attempts.count(self.training)):
            ep = self.attempt(item, k, learner.prompt(self, item, k))
            eps.append(ep)
            if self.training:
                learner.on_attempt(self, ep)
        g = Group(item["context"], eps, target=eps[0].target, item=item)
        learner.group_verdict(self, g)
        g.pick = learner.attempts.pick.__name__
        g.chosen = learner.attempts.pick(g, lambda answer: self.task.check(answer, item["target"]))
        if self.training:
            learner.on_question(self, g)
        return g

    def retry(self, memory, note):
        """Новая попытка текущего вопроса с показом из memory и заметкой — стрелка извлечение -> попытки
        (раунды рефлексии ACE). На её шагах не учатся."""
        p = self.learner.prompt(self, self.item, 0, memory)
        p.note = note
        training, self.training = self.training, False
        try:
            ep = self.attempt(self.item, 0, p)
        finally:
            self.training = training
        self.retried.append(ep)
        return ep

    def evaluate(self):
        """(верно, обрыв) по вопросам val без обучения. Одна и та же память не считается дважды; при случайном
        показе ключа нет и кэша тоже."""
        key = self.learner.key()
        if key is not None and key in self.scores:
            return self.scores[key]
        saved, self.training = (self.training, self.i, self.item), False
        try:
            out = []
            for self.i, self.item in enumerate(self.task.load("val")):
                out.append(self.result(self.question(self.item), self.item))
        finally:
            self.training, self.i, self.item = saved
        if key is not None:
            self.scores[key] = out
        return out

    def result(self, group, item):
        return self.task.check(group.answer, item["target"]), group.episodes[group.chosen].truncated


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


def entry(phase, epoch, i, g, item, correct, gated, memory_chars, sec, retried=()):
    """Запись лога по вопросу: ответ в зачёт, как выбран, вся группа и попытки из извлечения (раунды ACE)."""
    chosen = g.episodes[g.chosen]
    return dict(phase=phase, epoch=epoch, i=i, question=g.question, target=item["target"], answer=g.answer, correct=correct,
                pick=g.pick, pass_at_k=g.pass_at_k, vote=g.vote, finish=finish(chosen), output=chosen.output,
                shown=chosen.shown, read=chosen.used, gated=gated, memory_chars=memory_chars, sec=sec,
                group=[dict(k=e.k, answer=e.answer, ok=e.ok, temperature=e.prompt.temperature, finish=finish(e),
                            shown=e.shown, read=e.used, fired=e.fired, patches=[asdict(p) for p in e.patches])
                       for e in g.episodes],
                retries=[dict(answer=e.answer, ok=e.ok, finish=finish(e), note=e.prompt.note, output=e.output) for e in retried])


def failed(phase, epoch, i, item, error):
    """Запись лога о вопросе (или событии прохода), на котором прогон упал: неверно, с текстом ошибки."""
    return dict(phase=phase, epoch=epoch, i=i, question=item["context"] if item else "", target=item["target"] if item else "",
                answer="", correct=False, finish="error", error="".join(traceback.format_exception(error)), group=[])


def folder(task, n, learner, model):
    """Папка результатов: задача и размер, метод, протокол, модель и бэкенд — прогоны разных настроек не затирают
    друг друга."""
    tag = "_".join(x for x in (learner.protocol.name, model.name, getattr(model, "backend", "")) if x)
    return Path(config.RESULTS) / f"{task.name}{n}" / learner.name / tag


def run(task, learner, model, n=config.SIZE, out=None, split=""):
    """Прогон метода на задаче по протоколу ученика (learner.protocol). Онлайн: поток split, память учится по ходу,
    epochs проходов, в зачёт последний: первая попытка обучения, а с window — тест окна; до первого прохода —
    начальный тест всего потока (в лог). Офлайн: обучение на train, после каждого прохода val; тест на split с
    лучшей по val версией памяти (строго больше, при равенстве ранняя), без обучения. final — офлайн без val: тест
    памятью после последнего прохода, как итоговый агент апстрима. recheck — после обучения на вопросе ещё
    попытка новой памятью, только в лог.
    Лог и итог пишутся после каждого вопроса, память — в конце. Исключение на вопросе (или в событии прохода)
    уходит в лог записью finish="error", вопрос засчитывается неверным, прогон идёт дальше; в итоге — errors.
    Нарушение стыка сборки (Contract) прогон останавливает."""
    random.seed(config.SEED)
    learner = copy.deepcopy(learner)        # в реестре память ученика пуста: каждый прогон с чистой
    proto = learner.protocol
    proto.check(learner.name, learner.verdict, split)
    for part in ["train"] * proto.offline + ["val"] * (proto.val or learner.needs_val):
        try:
            task.load(part)
        except (FileNotFoundError, ValueError) as error:
            raise ValueError(f"{learner.name}: протоколу {proto.name} нужна выборка {part} задачи {task.name} — {error}")
    ex = Experiment(task, learner, model)
    log = []

    def summary(done):
        final = [r for r in log if r["phase"] == "test" or r["phase"] == "online" and r["epoch"] == proto.epochs - 1]
        return dict(task=task.name, method=learner.name, model=model.name, backend=getattr(model, "backend", ""),
                    n=len(final), protocol=proto.name, epochs=proto.epochs, offline=proto.offline, done=done,
                    errors=sum(r["finish"] == "error" for r in log), correct=sum(r["correct"] for r in final),
                    truncated=sum(r["finish"] == "length" for r in final),
                    accuracy=accuracy(task, [r["answer"] for r in final], [r["target"] for r in final]), **model.usage())

    def save(done=False, last=False):
        if out:
            Path(out).mkdir(parents=True, exist_ok=True)
            json.dump(log, open(f"{out}/log.json", "w"), ensure_ascii=False, indent=1)
            json.dump(summary(done), open(f"{out}/summary.json", "w"), indent=1)
            if last:
                json.dump(learner.dump(), open(f"{out}/memory.json", "w"), ensure_ascii=False, indent=1)

    def guarded(phase, i, item, step):
        """step() — вопрос или событие прохода; исключение — в лог, прогон дальше."""
        try:
            step()
        except Contract:
            raise
        except Exception as error:
            log.append(failed(phase, ex.epoch, i, item, error))
            print(f"{task.name} {learner.name} {phase}{ex.epoch} {i:3} ОШИБКА {error!r}", flush=True)
        save()

    def record(phase, i, g, item, t0, gated, retried=()):
        correct = task.check(g.answer, item["target"])
        log.append(entry(phase, ex.epoch, i, g, item, correct, gated, learner.memory.chars(), round(time.time() - t0, 1),
                         retried))
        done = [r for r in log if r["phase"] == phase and r["epoch"] == ex.epoch]
        print(f"{task.name} {learner.name} {phase}{ex.epoch} {i:3} {'+' if correct else '-'} "
              f"{sum(r['correct'] for r in done)}/{len(done)} mem={learner.memory.chars()}", flush=True)

    def test(phase, i, item):
        def step():
            t0, training = time.time(), ex.training
            ex.i, ex.item, ex.training = i, item, False
            try:
                record(phase, i, ex.question(item), item, t0, [])
            finally:
                ex.training = training
        guarded(phase, i, item, step)

    def train(i, item, batch):
        t0, gates, ex.retried = time.time(), len(learner.gated), []
        ex.i, ex.item = i, item
        if i % learner.every == 0:
            ex.batch = i // learner.every
            learner.on_batch_start(ex)
        g = ex.question(item)
        batch.append(g)
        if len(batch) == learner.every:
            learner.on_batch(ex, batch)
            batch.clear()
        record("train" if proto.offline or proto.window else "online", i, g, item, t0, learner.gated[gates:], ex.retried)

    def end_pass(epoch, batch):
        if batch and learner.flush:
            learner.on_batch(ex, batch)
        learner.on_pass(ex)
        if proto.val:
            score = sum(c for c, _ in ex.evaluate())
            print(f"val after epoch {epoch}: {score}", flush=True)
            versions.append((score, learner.snapshot()))

    done = False
    try:
        if proto.window:
            for i, item in enumerate(task.load(split, n)):
                test("initial", i, item)
        versions = []           # (верных на val, версия памяти) после каждого прохода
        for epoch in range(proto.epochs):
            items = learner.sample(ex, "train" if proto.offline else split, n)
            ex.epoch, ex.total, ex.batch, batch = epoch, len(items), 0, []
            guarded("pass", 0, None, lambda: learner.on_pass_start(ex))
            for i, item in enumerate(items):
                if proto.window and i % proto.window == 0:
                    for j in range(i, min(i + proto.window, len(items))):
                        test("online", j, items[j])
                guarded("train" if proto.offline or proto.window else "online", i, item, lambda: train(i, item, batch))
                if proto.recheck:
                    test("post", i, item)
            guarded("pass", len(items), None, lambda: end_pass(epoch, batch))
        if proto.offline:
            if versions:
                learner.restore(versions[best_index([v for v, _ in versions])][1])
            ex.training, ex.epoch = False, 0
            for i, item in enumerate(task.load(split, n)):
                test("test", i, item)
        done = True
    finally:
        save(done, last=True)           # прерванный прогон (Ctrl-C) — done=False, память на момент обрыва
    return summary(True)
