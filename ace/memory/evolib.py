"""Память EvoLib (EvoLib/EvoLib/evolib_agent.py, embed.py; промпты слияния evolib_merge_*.j2): библиотека skills и
insights.

    skills      подзадачи целиком (<subtask> с description, solution, result) из лучшего решения, если оно улучшает
    insights    «If ..., then ...»
    solutions   лучшее решение каждого вопроса — скрыто от решателя; меняется, только если новое улучшает

Журнал исходов записи — Future IG (fig), оценка при рождении — IG вопроса (ig, у skill). Эмбеддинг ключа (условие
insight, description skill) считается один раз, когда запись входит в библиотеку, и хранится при ней, как в
апстриме: запросы эмбеддингов (text-embedding-3-small на проводе) идут в его порядке — новый insight, все
description лучшего решения одним запросом, каждая слитая запись отдельно. Похожие (косинус строго больше 0.8) сливает
модель; одна слитая запись наследует журнал старой, а skill и IG — скользящим средним с долей 0.5. Вес записи для
показа задаёт решатель (solver/evolib.py)."""
from dataclasses import dataclass, field

import numpy as np

from .. import parse, prompts
from ..extract import ATTRIBUTION, BEST_ANSWER, IG
from ..extract.evolib import domain, future_gains, generate, llm_params, second_better
from ..model import Call, Reader, messages
from . import Container, Ids, Lessons, Operation, Record

P = {n: prompts.load(f"evolib_{n}") for n in ("merge_skills", "merge_insights", "compare")}
SIM, RATE = 0.8, 0.5        # порог слияния похожих, доля нового IG у слитого skill
EMBEDDING = "text-embedding-3-small"    # EmbeddingModel апстрима


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


def similarity(a, b):
    """embedding_similarity апстрима."""
    a, b = np.array(a), np.array(b)
    return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-8)


def graded(task, best):
    """Что проверка задачи видит как решение (eval_function апстрима): у hmmt — весь текст решения, у задач стенда —
    ответ FINAL ANSWER."""
    return best.output if task.name == "hmmt" else best.answer


class Library(Container):
    """skills и insights с общей нумерацией; solutions — лучшее решение каждого вопроса (решателю не видно)."""
    requires = frozenset({IG, BEST_ANSWER, ATTRIBUTION})

    def __init__(self):
        ids, ops = Ids(), Operation.ADD | Operation.DELETE      # delete — только при слиянии
        self.skills = Lessons("skill", Skill, ops, ids)
        self.insights = Lessons("insight", Insight, ops, ids)
        self.ids, self.solutions = ids, {}
        self.vecs = {}          # id -> эмбеддинг ключа записи
        self.born = {}          # id -> (контейнер, текст) всех записей, и ушедших: Future IG ищет запись по тексту

    def records(self):
        return sorted(self.skills.records() + self.insights.records(), key=lambda r: self.ids.order(r.id))

    def best(self, question):
        return self.solutions.get(question)

    def learn(self, ex, extractions):
        """insight, улучшение, лучшее решение и skills из него, Future IG — в таком порядке, как в run_iteration."""
        for x in extractions:
            for text in x.lessons:
                self.add_insight(ex, text)
            best = x.extras[BEST_ANSWER]
            if best is not None and self.improves(ex, x.group, best):
                self.solutions[x.group.question] = best
                self.add_skills(ex, parse.subtasks(best.output), x.extras[IG])
            # запись ищется по тексту, как в апстриме: слияние могло вернуть тот же текст новой записью
            for rid, gain in future_gains(x.extras[ATTRIBUTION], x.scores):
                container, text = self.born[rid]
                rec = next((r for r in container.records() if r.text == text), None)
                if rec is not None:
                    rec.outcomes.append(gain)

    def improves(self, ex, group, best):
        """is_improving апстрима: лучшего решения вопроса ещё нет или новое строго лучше по баллу; не лучше, но есть
        ответ большинства (без внешней оценки), а старое с ним не сходится — решает сравнение решений моделью."""
        before = self.best(group.question)
        if before is None or best.score > before.score:
            return True
        if not group.vote or ex.task.check(graded(ex.task, before), group.vote):
            return False
        prompt = P["compare"].fill(question=group.question, a=before.output, b=best.output, **domain(ex.task))
        return generate(ex.model, Call(messages(prompt), llm_params(ex.task), Reader(text=second_better))).output

    def embed(self, ex, texts):
        """embed_strings апстрима: пустая строка — "text"."""
        return ex.model.embed([t if t.strip() else "text" for t in texts], EMBEDDING) if texts else []

    def near(self, container, vec):
        """Записи контейнера с косинусом строго больше SIM, от самой похожей (при равенстве — в порядке библиотеки)."""
        sims = [(r, similarity(vec, self.vecs[r.id])) for r in container.records()]
        return [r for r, s in sorted([(r, s) for r, s in sims if s > SIM], key=lambda x: x[1], reverse=True)]

    def add(self, container, text, vec, **born):
        rec = container.add(text, **born)
        self.vecs[rec.id], self.born[rec.id] = vec, (container, text)

    def remove(self, container, rec):
        container.delete(rec.id)
        del self.vecs[rec.id]

    def ask(self, ex, name, reader, **fields):
        prompt = P[name].fill(**fields, **domain(ex.task))
        return generate(ex.model, Call(messages(prompt), llm_params(ex.task), reader)).output

    def add_insight(self, ex, text):
        """add_new_insight: похожего нет — запись добавляется; есть — ближайший сливает с новым модель: одна слитая
        запись наследует журнал старого, старый уходит; несколько — старый остаётся, новые делят один журнал.
        Тексты, уже лежащие в библиотеке, не добавляются."""
        vec = self.embed(ex, [condition(text)])[0]
        near = self.near(self.insights, vec)
        if not near:
            self.add(self.insights, text, vec, outcomes=[])
            return
        old = near[0]
        merged = self.ask(ex, "merge_insights", Reader(text=merged_insights), insights=f"{old.text}\n{text}")
        fig = []
        if len(merged) == 1:
            fig = old.outcomes
            self.remove(self.insights, old)
        for t in merged:
            if t not in {r.text for r in self.insights.records()}:
                self.add(self.insights, t, self.embed(ex, [condition(t)])[0], outcomes=fig)

    def add_skills(self, ex, blocks, ig):
        """add_new_skills: description всех подзадач — одним запросом эмбеддингов; каждая подзадача по очереди,
        как add_insight; у одной слитой — IG скользящим средним и журнал старой."""
        vecs = self.embed(ex, [doc for _, doc in blocks])
        for (block, doc), vec in zip(blocks, vecs):
            near = self.near(self.skills, vec)
            if not near:
                self.add(self.skills, block, vec, doc=doc, ig=ig, outcomes=[])
                continue
            old = near[0]
            merged = self.ask(ex, "merge_skills", Reader(text=parse.subtasks), skills=f"{old.text}\n{block}")
            new_ig, fig = ig, []
            if len(merged) == 1:
                new_ig, fig = RATE * ig + (1 - RATE) * old.ig, old.outcomes
                self.remove(self.skills, old)
            for b, d in merged:
                if b not in {r.text for r in self.skills.records()}:
                    self.add(self.skills, b, self.embed(ex, [d])[0], doc=d, ig=new_ig, outcomes=fig)

    def dump(self):
        solutions = [dict(kind="best", id=f"b{i}", question=q, text=s.output, answer=s.answer, score=s.score)
                     for i, (q, s) in enumerate(self.solutions.items(), 1)]
        return self.skills.dump() + self.insights.dump() + solutions
