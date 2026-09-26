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

Случайность одна — random.Random(seed) апстрима: выбор родителя, затем перемешивание train на новой эпохе.
В конце прохода у ученика — лучший по val кандидат пула (при равенстве ранний), и цикл берёт его версией прохода:
лучшая по val версия прогона — тот же кандидат, что result.best_candidate апстрима."""
import random
from collections import Counter
from dataclasses import dataclass, field

from ..loop import Version, best_index, evaluated
from . import Wrapper

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
class Iteration:
    """След итерации (full_program_trace): родитель, минибатч, оценки на нём до и после, принятый потомок."""
    parent: int
    ids: list
    before: list = field(default_factory=list)
    after: list = None
    child: int = None


class Evolution(Wrapper):
    def __init__(self, inner, budget, seed=0, name=None):
        super().__init__(inner, name)
        self.budget = budget            # max_metric_calls
        self.rng = random.Random(seed)
        self.sampler = EpochShuffled(inner.every, self.rng)
        self.pool = []                  # Candidate по номерам
        self.front = {}                 # номер вопроса val -> лучшая оценка (pareto_front_valset)
        self.at_front = {}              # номер вопроса val -> номера кандидатов с ней (program_at_pareto_front_valset)
        self.calls = 0                  # total_num_evals
        self.i = -1                     # номер итерации (state.i)
        self.trace = []                 # Iteration по порядку
        self.current = 0                # номер кандидата в памяти ученика; None — потомок, ещё не в пуле

    def check(self):
        if not self.inner.protocol.val:
            raise ValueError(f"{self.name}: GEPA — только офлайн с val (пул оценивается на val)")

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
        """Начало итерации: seed на val (до первой), проверка бюджета, родитель, минибатч."""
        if not self.pool:
            self.add(ex, [None])
        if self.calls >= self.budget:
            return []
        self.i += 1
        parent = pareto_parent(self.at_front, [c.average for c in self.pool], self.rng)
        self.take(parent)
        train = ex.task.load(split, n)
        ids = self.sampler.next(len(train), self.i)
        self.trace.append(Iteration(parent, ids))
        return [train[j] for j in ids]

    def add(self, ex, parents):
        """Память ученика — новым кандидатом: весь val, пул, Парето-фронт (update_state_with_new_program)."""
        idx = len(self.pool)
        self.current = idx
        version = evaluated(ex, self.inner, dump=True)
        self.calls += len(version.val)
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
        """Минибатч родителя решён: рефлексия, потомок на том же минибатче, принятие строго лучшего."""
        it = self.trace[-1]
        parent = self.current
        it.before = [score(g) for g in groups]
        self.calls += len(groups)
        if all(s >= PERFECT for s in it.before):
            return
        key = self.inner.key()
        self.inner.on_batch(ex, groups)
        if self.inner.key() == key:     # рефлексия не дала текста — потомка нет
            return
        self.current = None
        with ex.frozen():
            it.after = [score(ex.question(g.item)) for g in groups]
        self.calls += len(groups)
        if sum(it.after) > sum(it.before):
            it.child = self.add(ex, [parent])
        else:
            self.take(parent)

    def on_pass(self, ex):
        """Конец итерации: у ученика — лучший по val кандидат пула (FullEvaluationPolicy.get_best_program)."""
        self.inner.on_pass(ex)
        self.take(self.best())

    def best(self):
        return best_index([c.average for c in self.pool])

    def dump(self):
        pool = [dict(kind="candidate", id=i, memory=c.version.dump, parents=c.parents, scores=c.scores)
                for i, c in enumerate(self.pool)]
        return self.inner.dump() + pool + [dict(kind="best", id=self.best())] if self.pool else self.inner.dump()


def score(group):
    """Оценка вопроса: 1.0 — ответ в зачёт верен."""
    return float(bool(group.episodes[group.chosen].ok))


class EpochShuffled:
    """EpochShuffledBatchSampler: номера train перемешиваются в начале эпохи и добиваются до кратного размеру
    минибатча самыми редкими; минибатч итерации i — кусок с i * size по кругу."""
    def __init__(self, size, rng):
        self.size = size
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

    def next(self, n, i):
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
    front = without_dominated(at_front, averages)
    frequency = {}
    for programs in front.values():
        for p in programs:
            frequency[p] = frequency.get(p, 0) + 1
    sampling = [p for p, f in frequency.items() for _ in range(f)]
    return rng.choice(sampling)


def dominated(y, others, at_front):
    """is_dominated: на каждом вопросе, где y на фронте, там же есть кто-то из others."""
    return all(any(p in others for p in programs) for programs in at_front.values() if y in programs)


def without_dominated(at_front, averages):
    """remove_dominated_programs: от худших по среднему к лучшим убирается по одному доминируемому, пока есть."""
    frequency = {}
    for programs in at_front.values():
        for p in programs:
            frequency[p] = frequency.get(p, 0) + 1
    programs = sorted(frequency, key=lambda p: averages[p])
    gone = set()
    found = True
    while found:
        found = False
        for y in programs:
            if y in gone:
                continue
            if dominated(y, set(programs).difference({y}).difference(gone), at_front):
                gone.add(y)
                found = True
                break
    return {j: {p for p in programs_ if p not in gone} for j, programs_ in at_front.items()}
