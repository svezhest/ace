"""GEPA: мета-уровень — пул кандидатов с оценками по вопросам val, Парето-выбор родителя, принятие по минибатчу
(gepa-ai/gepa d771eb21b5: core/engine.py GEPAEngine.run, core/state.py GEPAState, proposer/reflective_mutation/
reflective_mutation.py propose, strategies/ candidate_selector ParetoCandidateSelector, batch_sampler
EpochShuffledBatchSampler, acceptance StrictImprovementAcceptance, eval_policy FullEvaluationPolicy; gepa_utils.py
select_program_candidate_from_pareto_front).

    Evolution(ученик, budget, seed)   итерация = проход по минибатчу (батч ученика, every вопросов): родитель — с
                                      Парето-фронта, минибатч — из перемешанного по эпохам train, вопросы — попытки
                                      ученика памятью родителя, рефлексия — извлечение ученика на батче, потомок —
                                      память после неё; потомок снова решает минибатч и, если верных строго больше,
                                      решает весь val и входит в пул; обучение кончается, когда вызовов метрики
                                      (попыток на вопросах) не меньше budget

Случайность одна — random.Random(seed) апстрима: выбор родителя, затем перемешивание train на новой эпохе; seed
None — SEED стенда на старте прогона. Минибатч — every ученика (и после swap), вопросы — из выборки ученика.
В конце прохода у ученика — лучший по val кандидат пула (при равенстве ранний), и цикл берёт его версией прохода:
лучшая по val версия прогона — тот же кандидат, что result.best_candidate апстрима."""
import random
from collections import Counter
from dataclasses import asdict, dataclass, field

from .. import config
from ..loop import Version, best_index, evaluated
from . import Wrapper, single_meta

PERFECT = 1.0               # perfect_score; skip_perfect_score — минибатч родителя весь верен, рефлексии нет


@dataclass
class Candidate:
    """Кандидат пула: версия памяти ученика (снимок, оценки по вопросам val, дамп на момент снимка) и родители."""
    version: Version
    parents: list

    @property
    def memory(self):
        return self.version.memory

    @property
    def scores(self):
        """Номер вопроса val -> 1.0 / 0.0."""
        return self.version.scores

    @property
    def average(self):
        return self.version.share


@dataclass
class Proposal:
    """Предложение итерации (след full_program_trace): родитель, минибатч, оценки на нём до и после, принятый
    потомок."""
    parent: int
    ids: list
    before: list = field(default_factory=list)
    after: list = None
    child: int = None


class Evolution(Wrapper):
    iterates = True

    def __init__(self, inner, budget, seed=None, name=None):
        super().__init__(inner, name)
        self.budget = budget            # max_metric_calls
        self.seed = seed                # None — config.SEED на старте прогона
        self.rng = random.Random(seed)
        self.sampler = EpochShuffled(self.rng)
        self.pool = []                  # Candidate по номерам
        self.front = {}                 # номер вопроса val -> лучшая оценка (pareto_front_valset)
        self.at_front = {}              # номер вопроса val -> номера кандидатов с ней (program_at_pareto_front_valset)
        self.calls = 0                  # total_num_evals
        self.iteration = -1             # номер итерации (state.i)
        self.trace = []                 # Proposal по порядку
        self.current = 0                # номер кандидата в памяти ученика; None — потомок, ещё не в пуле

    def check(self):
        """Ученик, над которым потомок GEPA — не память после обучения на минибатче или бюджет не тот, — ошибка
        сборки."""
        single_meta(self)
        inner = self.inner
        if not inner.protocol.val:
            raise ValueError(f"{self.name}: GEPA — только офлайн с val (пул оценивается на val)")
        if not inner.learns:
            raise ValueError(f"{self.name}: GEPA над учеником, который не учится (нет извлечения), — потомков не будет")
        if inner.extract is not None and inner.extract.steps:
            raise ValueError(f"{self.name}: GEPA — извлечение на шаге правит память посреди минибатча, и оценка на нём "
                             "была бы не родителя")
        if inner.protocol.recheck:
            raise ValueError(f"{self.name}: GEPA — recheck тратит попытки вне бюджета вызовов метрики")

    def state(self):
        """Кандидат — по месту в пуле (и в ключе): у двух кандидатов с одним текстом оценки свои, как у апстрима без
        кэша."""
        return self.current

    def restore_state(self, state):
        self.current = state

    def state_key(self):
        return self.current

    def take(self, idx):
        """Кандидат пула — в память ученика."""
        self.restore((self.pool[idx].memory, idx))

    def sample(self, ex, split, n):
        """Начало итерации: seed на val (до первой), проверка бюджета, родитель, минибатч из выборки ученика."""
        if not self.pool:
            self.rng.seed(config.SEED if self.seed is None else self.seed)
            self.add(ex, [None])
        if self.calls >= self.budget:
            return []
        self.iteration += 1
        parent = pareto_parent(self.at_front, [c.average for c in self.pool], self.rng)
        self.take(parent)
        train = self.inner.sample(ex, split, n)
        ids = self.sampler.next(len(train), self.iteration, self.inner.every)
        self.trace.append(Proposal(parent, ids))
        return [train[j] for j in ids]

    def add(self, ex, parents):
        """Память ученика — новым кандидатом: весь val, пул, Парето-фронт (update_state_with_new_program)."""
        idx = len(self.pool)
        self.current = idx
        version = evaluated(ex, self.inner, dump=True)
        self.calls += len(version.val) * self.inner.attempts.count(False)
        self.pool.append(Candidate(version, parents))
        for j, score in version.scores.items():
            best = self.front.get(j, float("-inf"))
            if score > best:
                self.front[j] = score
                self.at_front[j] = {idx}
            elif score == best:
                self.at_front.setdefault(j, set()).add(idx)
        return idx

    def on_batch(self, ex, groups):
        """Минибатч родителя решён: обучение ученика на нём (рефлексия), потомок — память после него; потомок решает
        тот же минибатч без обучения и, если верных строго больше, входит в пул. Оценка — ex.solved (проверка
        задачи, метрика апстрима), а не вердикт попытки. Ученик ничего не выучил (рефлексия не дала текста) —
        потомка нет. Минибатч родителя весь верен — обучения нет; извлечённое на вопросах до батча ученик
        отбросит в конце прохода (итерации)."""
        it = self.trace[-1]
        parent = self.current
        it.before = [float(ex.solved(g)) for g in groups]
        self.calls += attempts(groups)
        if all(s >= PERFECT for s in it.before):
            return
        version = self.inner.version()
        self.inner.on_batch(ex, groups)
        if self.inner.version() == version:
            return
        self.current = None
        again = [ex.answer(g.i, g.item) for g in groups]
        it.after = [float(ex.solved(g)) for g in again]
        self.calls += attempts(again)
        if sum(it.after) > sum(it.before):
            it.child = self.add(ex, [parent])
        else:
            self.take(parent)

    def on_pass(self, ex):
        """Конец итерации: у ученика — лучший по val кандидат пула (FullEvaluationPolicy.get_best_program)."""
        self.inner.on_pass(ex)
        self.take(self.best_candidate())

    def best_candidate(self):
        return best_index([c.average for c in self.pool])

    def dump(self):
        """Память ученика, пул кандидатов, след итераций (full_program_trace) и лучший."""
        if not self.pool:
            return self.inner.dump()
        pool = [dict(kind="candidate", id=i, memory=c.version.dump, parents=c.parents, scores=c.scores)
                for i, c in enumerate(self.pool)]
        trace = [dict(kind="iteration", id=i, **asdict(it)) for i, it in enumerate(self.trace)]
        return self.inner.dump() + pool + trace + [dict(kind="best", id=self.best_candidate())]


def attempts(groups):
    """Вызовов метрики: попыток на вопросах (у ученика с группой попыток — все)."""
    return sum(len(g.episodes) for g in groups)


class EpochShuffled:
    """EpochShuffledBatchSampler: номера train перемешиваются в начале эпохи и добиваются до кратного размеру
    минибатча самыми редкими; минибатч итерации i — кусок с i * size по кругу."""
    def __init__(self, rng):
        self.size = 0
        self.rng = rng
        self.shuffled = []
        self.epoch = -1
        self.freqs = Counter()
        self.last = 0               # размер train при прошлом перемешивании

    def shuffle(self, n):
        self.last = n
        self.shuffled = list(range(n))
        self.rng.shuffle(self.shuffled)
        self.freqs = Counter(self.shuffled)
        pad = (self.size - n % self.size) % self.size
        for _ in range(pad):
            rare = self.freqs.most_common()[::-1][0][0]
            self.shuffled.append(rare)
            self.freqs[rare] += 1

    def next(self, n, i, size):
        """Минибатч итерации i из train на n вопросов; size — размер минибатча (every ученика)."""
        self.size = size
        base = i * self.size
        epoch = 0 if self.epoch == -1 else base // max(len(self.shuffled), 1)
        if not self.shuffled or n != self.last or epoch > self.epoch:
            self.epoch = epoch
            self.shuffle(n)
        base %= len(self.shuffled)
        return self.shuffled[base:base + self.size]


def pareto_parent(at_front, averages, rng):
    """select_program_candidate_from_pareto_front: без доминируемых кандидатов фронта, кандидат — случайно с весом
    «на скольких вопросах val он на фронте»."""
    frequency = on_front(without_dominated(at_front, averages))
    sampling = [p for p, f in frequency.items() for _ in range(f)]
    return rng.choice(sampling)


def on_front(at_front):
    """Кандидат -> на скольких вопросах val он на фронте; порядок — первого появления, как у словаря апстрима."""
    return Counter(p for programs in at_front.values() for p in programs)


def dominated(y, others, at_front):
    """is_dominated: на каждом вопросе, где y на фронте, там же есть кто-то из others."""
    return all(any(p in others for p in programs) for programs in at_front.values() if y in programs)


def without_dominated(at_front, averages):
    """remove_dominated_programs: от худших по среднему к лучшим убирается по одному доминируемому, пока есть."""
    programs = sorted(on_front(at_front), key=lambda p: averages[p])
    gone = set()
    while True:
        y = next((y for y in programs if y not in gone
                  and dominated(y, set(programs) - {y} - gone, at_front)), None)
        if y is None:
            break
        gone.add(y)
    return {j: {p for p in ps if p not in gone} for j, ps in at_front.items()}
