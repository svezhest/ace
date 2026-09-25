"""EvoLib (EvoLib/EvoLib/evolib_agent.py, вариант HMMT из eval_main.py: без синтетических тестов). Промпты
ace/prompts/evolib_*.j2: апстрим, из которого убрано только «math».

    попытки     3 при T = 0; различаются выборкой памяти (одно случайное число на попытку выбирает ветку показа)
    в зачёт     ответ большинства
    вердикт     попытки — нет; группы — голосование (попытка «верна», если её ответ совпал с ответом большинства)
    извлечение  баллы, IG, insight, улучшение, сравнение решений (extract/evolib.py)
    память      библиотека: skills — подзадачи целиком (<subtask> с description, solution, result) из лучшего
                решения, если оно улучшает; insights «If ..., then ...». Журнал исходов записи — Future IG
                (fig), оценка при рождении — IG вопроса (ig, у skill). Похожие (косинус строго больше 0.8 по
                условию insight или description skill) сливает модель; одна слитая запись наследует журнал
                старой, а skill и IG — скользящим средним с долей 0.5. Лучшее решение вопроса — скрыто от
                решателя
    показ       p < 0.4 — до 10 skills, p < 0.7 — до 10 insights, иначе ничего (пустая ветка отдаёт ход
                следующей); выборка с возвращением по весу; к системному промпту — просьба решать подзадачами
evolib_judge — баллы от судьи (вердикт попытки judge): insight только при неудаче лучшей, без деления баллов,
    без сравнения решений.

Вес задаёт метод, библиотека его не знает: skill — w_IG * max(IG, eps) + (среднее fig или 0.5), insight —
max(среднее fig или 0.5, eps). В апстриме у skill пола нет: отрицательный вес ломает random.choices молча,
поэтому здесь пол eps. Эпох в апстриме тысячи (5000 итераций по кругу), у нас это параметр протокола EPOCHS."""
from dataclasses import dataclass, field

from .. import embed, parse, prompts, render, verdict
from ..extract import ATTRIBUTION, BEST_ANSWER, IG
from ..extract.evolib import EPS, Gains, future_gains
from ..learner import Learner, swap
from ..loop import Attempts, vote
from ..memory import Ids, Lessons, Operation, Record
from ..show import Choose, Sample, Show

P = {n: prompts.load(f"evolib_{n}") for n in ("merge_skills", "merge_insights")}
K, W_IG = 10, 1.0
LEGACY_W_IG = 100           # при w_IG от 100 апстрим не прибавляет Future IG к весу skill
FIG_PRIOR = 0.5             # Future IG записи, которая ещё ни разу не была в промпте лучшей попытки
P_SKILLS, P_INSIGHTS = 0.4, 0.7     # накопленные вероятности веток показа
SIM, RATE = 0.8, 0.5        # порог слияния похожих, доля нового IG у слитого skill
ATTEMPTS = 3                # k_q_per_problem


@dataclass(frozen=True, eq=False)
class Insight(Record):
    """«If ..., then ...»; outcomes — журнал Future IG: прирост лучшей попытки над попытками без записи, по разу
    на каждое её появление в промпте лучшей. Слитые одним ответом записи делят один журнал, как в апстриме."""
    outcomes: list = field(default_factory=list)


@dataclass(frozen=True, eq=False)
class Skill(Insight):
    """Подзадача целиком; doc — её <description>...</description> с тегами, по нему ищутся похожие; ig — IG вопроса
    при рождении."""
    doc: str = ""
    ig: float = 0.0


def future(r):
    return sum(r.outcomes) / len(r.outcomes) if r.outcomes else FIG_PRIOR


def skill_weight(r, w_ig=W_IG):
    w = w_ig * max(r.ig, EPS)
    return max(w + future(r) if w_ig < LEGACY_W_IG else w, EPS)


def insight_weight(r):
    return max(future(r), EPS)


def condition(insight):
    return insight.split(", then ")[0].replace("If ", "").strip()


def merged_insights(text):
    """Строки «If ...» из всех блоков ```insights ответа слияния (consolidate_insights апстрима)."""
    return [l.strip() for l in parse.fenced(text, "insights").split("\n") if l.strip().startswith("If ")]


class Library:
    """skills и insights с общей нумерацией; solutions — лучшее решение каждого вопроса (решателю не видно)."""
    requires = frozenset({IG, BEST_ANSWER, ATTRIBUTION})

    def __init__(self):
        ids, ops = Ids(), Operation.ADD | Operation.DELETE      # delete — только при слиянии
        self.skills = Lessons("skill", Skill, ops, ids)
        self.insights = Lessons("insight", Insight, ops, ids)
        self.ids, self.solutions = ids, {}

    def records(self):
        return sorted(self.skills.records() + self.insights.records(), key=lambda r: self.ids.order(r.id))

    def get(self, id):
        return self.skills.get(id) or self.insights.get(id)

    def best(self, question):
        return self.solutions.get(question)

    def learn(self, ex, extractions):
        """insight, лучшее решение и skills из него (если улучшает), Future IG — в таком порядке, как в апстриме."""
        for x in extractions:
            for text in x.lessons:
                self.add_insight(ex, text)
            best = x.extras[BEST_ANSWER]
            if best:
                self.solutions[x.group.question] = best
                for block, doc in parse.subtasks(best.output):
                    self.add_skill(ex, block, doc, x.extras[IG])
            for rid, gain in future_gains(x.extras[ATTRIBUTION], x.scores):
                if self.get(rid):
                    self.get(rid).outcomes.append(gain)

    def add_insight(self, ex, text):
        def merge(old):
            out = ex.model.one("", P["merge_insights"].fill(insights=f"{old.text}\n{text}")).output or ""
            fig = []
            return [(t, dict(outcomes=fig)) for t in merged_insights(out)]
        self.consolidate(self.insights, text, condition(text), lambda r: condition(r.text), dict(outcomes=[]), merge,
                         lambda old, born: dict(outcomes=old.outcomes))

    def add_skill(self, ex, block, doc, ig):
        def merge(old):
            out = ex.model.one("", P["merge_skills"].fill(skills=f"{old.text}\n{block}")).output or ""
            fig = []
            return [(b, dict(doc=d, ig=ig, outcomes=fig)) for b, d in parse.subtasks(out)]
        self.consolidate(self.skills, block, doc, lambda r: r.doc, dict(doc=doc, ig=ig, outcomes=[]), merge,
                         lambda old, born: dict(born, ig=RATE * born["ig"] + (1 - RATE) * old.ig, outcomes=old.outcomes))

    def consolidate(self, container, text, key, key_of, born, merge, inherit):
        """Похожих (косинус ключей строго больше SIM) нет — запись добавляется. Есть — ближайшую сливает с новой
        модель: одна слитая запись наследует от старой (inherit), старая уходит; несколько — старая остаётся.
        Тексты, уже лежащие в контейнере, не добавляются."""
        same = container.records()
        near = []
        if same:
            sims = embed.embed([key_of(r) for r in same]) @ embed.embed([key])[0]
            near = [same[i] for i in sims.argsort()[::-1] if sims[i] > SIM]
        if not near:
            container.add(text, **born)
            return
        old = near[0]
        merged = merge(old)
        if len(merged) == 1:
            merged = [(t, inherit(old, b)) for t, b in merged]
            container.delete(old.id)
        for t, b in merged:
            if t not in {r.text for r in container.records()}:
                container.add(t, **b)

    def __len__(self):
        return len(self.records())

    def chars(self):
        return sum(len(r.text) for r in self.records())

    def key(self):
        return tuple(r.text for r in self.records())

    def dump(self):
        solutions = [dict(kind="best", id=f"b{i}", question=q, text=s.output, answer=s.answer, score=s.score)
                     for i, (q, s) in enumerate(self.solutions.items(), 1)]
        return self.skills.dump() + self.insights.dump() + solutions


class Part(Show):
    """Показ над частью памяти part(память)."""
    def __init__(self, part, show):
        self.part, self.show, self.random = part, show, show.random

    def prompt(self, ex, memory, item, k):
        return self.show.prompt(ex, self.part(memory), item, k)


class Hint(Show):
    """Добавка к системному промпту решателя перед показом (решать подзадачами)."""
    def __init__(self, hint, show):
        self.hint, self.show, self.random = hint, show, show.random

    def prompt(self, ex, memory, item, k):
        p = self.show.prompt(ex, memory, item, k)
        p.system = self.hint + p.system
        return p


def sample(k, weight, intro):
    return Sample(k, weight, line=render.plain, head="", before=prompts.text(intro))


def show(k=K, w_ig=W_IG):
    """Выборка из библиотеки (_sample_from_library апстрима): k записей ветки, вес skill с w_ig."""
    return Hint(prompts.text("evolib_subtasks"), Choose(
        (P_SKILLS, Part(lambda m: m.skills, sample(k, lambda r: skill_weight(r, w_ig), "evolib_skills_intro"))),
        (P_INSIGHTS, Part(lambda m: m.insights, sample(k, insight_weight, "evolib_insights_intro")))))


SHOW = show()

evolib = Learner("evolib", memory=Library(), show=SHOW, extract=Gains(), attempts=Attempts(ATTEMPTS, pick=vote),
                 verdict=verdict.none, group_verdict=verdict.vote)
evolib_judge = swap(evolib, "evolib_judge", extract=Gains(evaluated=True), verdict=verdict.judge, group_verdict=verdict.none)
