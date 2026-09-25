"""Память EvoLib (EvoLib/EvoLib/evolib_agent.py; промпты слияния evolib_merge_*.j2): библиотека skills и insights.

    skills      подзадачи целиком (<subtask> с description, solution, result) из лучшего решения, если оно улучшает
    insights    «If ..., then ...»
    solutions   лучшее решение каждого вопроса — скрыто от решателя (его читает извлечение для сравнения)

Журнал исходов записи — Future IG (fig), оценка при рождении — IG вопроса (ig, у skill). Похожие (косинус
строго больше 0.8 по условию insight или description skill) сливает модель; одна слитая запись наследует журнал
старой, а skill и IG — скользящим средним с долей 0.5. Вес записи для показа задаёт показ (show/evolib.py)."""
from dataclasses import dataclass, field

from .. import embed, parse, prompts
from ..extract import ATTRIBUTION, BEST_ANSWER, IG
from ..extract.evolib import future_gains
from . import Container, Ids, Lessons, Operation, Record

P = {n: prompts.load(f"evolib_{n}") for n in ("merge_skills", "merge_insights")}
SIM, RATE = 0.8, 0.5        # порог слияния похожих, доля нового IG у слитого skill


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


def condition(insight):
    return insight.split(", then ")[0].replace("If ", "").strip()


def merged_insights(text):
    """Строки «If ...» из всех блоков ```insights ответа слияния (consolidate_insights апстрима)."""
    return [l.strip() for l in parse.fenced(text, "insights").split("\n") if l.strip().startswith("If ")]


class Library(Container):
    """skills и insights с общей нумерацией; solutions — лучшее решение каждого вопроса (решателю не видно)."""
    requires = frozenset({IG, BEST_ANSWER, ATTRIBUTION})

    def __init__(self):
        ids, ops = Ids(), Operation.ADD | Operation.DELETE      # delete — только при слиянии
        self.skills = Lessons("skill", Skill, ops, ids)
        self.insights = Lessons("insight", Insight, ops, ids)
        self.ids, self.solutions = ids, {}

    def records(self):
        return sorted(self.skills.records() + self.insights.records(), key=lambda r: self.ids.order(r.id))

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

    def dump(self):
        solutions = [dict(kind="best", id=f"b{i}", question=q, text=s.output, answer=s.answer, score=s.score)
                     for i, (q, s) in enumerate(self.solutions.items(), 1)]
        return self.skills.dump() + self.insights.dump() + solutions
