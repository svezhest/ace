"""Цикл, один на все методы. Эксперимент — проходы по задачам; вопрос — группа попыток; попытка — шаги
решателя. Ученик (learner.py) даёт промпт попытки и отвечает на события своих масштабов:

    шаг       on_step(ex, attempt, step) -> Patch | None     при обучении и на val / тесте
    попытка   prompt(ex, item, k) -> Prompt до, on_attempt(ex, episode) после
    вопрос    on_question(ex, group)                        группа есть всегда, обычно из одной попытки
    батч      on_batch(ex, groups) раз в learner.every вопросов; неполный в конце прохода — если learner.flush
    проход    on_pass(ex); ex.evaluate() — точность на val

На val и тесте (training = False) цикл зовёт только prompt и on_step. Сам цикл делает: среду попытки,
вердикты (верный ответ в эпизоде только при golden), выбор ответа в зачёт, запись прочитанного
инструментами (episode.used), протокол (онлайн; офлайн с выбором лучшей по val версии) и лог."""
import copy
import json
import random
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import config, render
from .model import Call, messages, params
from .tasks import accuracy, final_answer
from .verdict import majority


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


class Experiment:
    """Метод × задача. Хукам ученика — как ex: модель, задача, флаг обучения, номер вопроса и их число,
    evaluate() и retry()."""
    def __init__(self, task, learner, model):
        self.task, self.learner, self.model = task, learner, model
        self.training, self.epoch, self.i, self.total, self.item = True, 0, 0, 0, None
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
                     list(prompt.deps.reads) if prompt.deps is not None else [], a.fired, a.patches, system=a.system)
        self.learner.verdict(self, ep, item["target"])
        return ep

    def solved(self, item, k, prompt):
        """Попытка своим решателем метода: без инструментов, один вызов или разговор метода."""
        solver = prompt.solver
        call = solver.call(prompt.note)
        reply = solver.talk(self.model, call) if solver.talk else self.model.ask(call)
        final = reply.output or ""
        ep = Episode(item["context"], k, prompt, reply.text, final, solver.answer(final), [], reply.truncated,
                     [], [], [])
        self.learner.verdict(self, ep, item["target"])
        return ep

    def stepper(self, a):
        """on_step для модели: каждый новый шаг — ученику; его Patch-и одного запроса сливаются."""
        def on_step(new):
            patch = None
            for step in new:
                a.steps.append(step)
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
        g = Group(item["context"], eps, target=eps[0].target)
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
            return self.attempt(self.item, 0, p)
        finally:
            self.training = training

    def evaluate(self):
        """(верно, обрыв) по вопросам val без обучения. Одна и та же память не считается дважды; при случайном
        показе ключа нет и кэша тоже."""
        key = self.learner.key()
        if key is not None and key in self.scores:
            return self.scores[key]
        training, self.training = self.training, False
        try:
            out = [self.result(self.question(item), item) for item in self.task.load("val")]
        finally:
            self.training = training
        if key is not None:
            self.scores[key] = out
        return out

    def result(self, group, item):
        return self.task.check(group.answer, item["target"]), group.episodes[group.chosen].truncated


def finish(ep):
    return "length" if ep.truncated else "stop"


def entry(phase, epoch, i, g, item, correct, gated, memory_chars, sec):
    """Запись лога по вопросу: ответ в зачёт, как выбран, и вся группа."""
    chosen = g.episodes[g.chosen]
    return dict(phase=phase, epoch=epoch, i=i, question=g.question, target=item["target"], answer=g.answer, correct=correct,
                pick=g.pick, pass_at_k=g.pass_at_k, vote=g.vote, finish=finish(chosen), output=chosen.output,
                shown=chosen.shown, read=chosen.used, gated=gated, memory_chars=memory_chars, sec=sec,
                group=[dict(k=e.k, answer=e.answer, ok=e.ok, temperature=e.prompt.temperature, finish=finish(e),
                            shown=e.shown, read=e.used, fired=e.fired, patches=[asdict(p) for p in e.patches])
                       for e in g.episodes])


def run(task, learner, model, n=config.SIZE, out=None, split="", epochs=None, offline=False):
    """Онлайн: поток split, память учится по ходу, epochs проходов, в зачёт последний. В зачёт первая попытка
    обучения, а с learner.window (ACE online) — тест окна: перед обучением на каждых window вопросах они решаются
    текущей памятью без обучения; до первого прохода — начальный тест всего потока (в лог).
    Офлайн (ACE offline, MCE): обучение на train, после каждого прохода val; тест на split с лучшей по val
    версией памяти (строго больше, при равенстве ранняя), без обучения. learner.final (TF-GRPO) — всегда офлайн
    и без val: тест памятью после последнего прохода, как итоговый агент апстрима.
    learner.recheck — после обучения на вопросе ещё попытка новой памятью, только в лог (ACE post_train)."""
    random.seed(config.SEED)
    learner = copy.deepcopy(learner)        # в реестре память ученика пуста: каждый прогон с чистой
    offline = offline or learner.final
    ex = Experiment(task, learner, model)
    epochs = epochs or learner.epochs
    log = []

    def record(phase, i, g, item, t0, gated):
        correct = task.check(g.answer, item["target"])
        log.append(entry(phase, ex.epoch, i, g, item, correct, gated, learner.memory.chars(), round(time.time() - t0, 1)))
        done = [r for r in log if r["phase"] == phase and r["epoch"] == ex.epoch]
        print(f"{task.name} {learner.name} {phase}{ex.epoch} {i:3} {'+' if correct else '-'} "
              f"{sum(r['correct'] for r in done)}/{len(done)} mem={learner.memory.chars()}", flush=True)

    def test(phase, i, item):
        t0, training = time.time(), ex.training
        ex.i, ex.item, ex.training = i, item, False
        try:
            record(phase, i, ex.question(item), item, t0, [])
        finally:
            ex.training = training

    window = 0 if offline else learner.window
    if window:
        for i, item in enumerate(task.load(split)[:n]):
            test("initial", i, item)
    best, best_val = learner.snapshot(), -1
    for epoch in range(epochs):
        items = task.load("train" if offline else split)[:n]
        ex.epoch, ex.total, batch = epoch, len(items), []
        for i, item in enumerate(items):
            if window and i % window == 0:
                for j in range(i, min(i + window, len(items))):
                    test("online", j, items[j])
            t0, gates = time.time(), len(learner.gated)
            ex.i, ex.item = i, item
            g = ex.question(item)
            batch.append(g)
            if len(batch) == learner.every:
                learner.on_batch(ex, batch)
                batch = []
            record("train" if offline or window else "online", i, g, item, t0, learner.gated[gates:])
            if learner.recheck:
                test("post", i, item)
        if batch and learner.flush:
            learner.on_batch(ex, batch)
        learner.on_pass(ex)
        if offline and not learner.final:
            score = sum(c for c, _ in ex.evaluate())
            print(f"val after epoch {epoch}: {score}", flush=True)
            if score > best_val:
                best, best_val = learner.snapshot(), score
    if offline:
        if not learner.final:
            learner.restore(best)
        ex.training, ex.epoch = False, 0
        for i, item in enumerate(task.load(split)[:n]):
            t0 = time.time()
            ex.i, ex.item = i, item
            record("test", i, ex.question(item), item, t0, [])
    final = [r for r in log if r["phase"] == "test" or r["phase"] == "online" and r["epoch"] == epochs - 1]
    summary = dict(task=task.name, method=learner.name, model=model.name, n=len(final), epochs=epochs, offline=offline,
                   correct=sum(r["correct"] for r in final), truncated=sum(r["finish"] == "length" for r in final),
                   accuracy=accuracy(task, [r["answer"] for r in final], [r["target"] for r in final]), **model.usage())
    if out:
        Path(out).mkdir(parents=True, exist_ok=True)
        json.dump(log, open(f"{out}/log.json", "w"), ensure_ascii=False, indent=1)
        json.dump(summary, open(f"{out}/summary.json", "w"), indent=1)
        json.dump(learner.dump(), open(f"{out}/memory.json", "w"), ensure_ascii=False, indent=1)
    return summary
