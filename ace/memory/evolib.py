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

from .. import parse, prompts, render
from ..extract import ATTRIBUTION, BEST_ANSWER, IG
from ..upstream.evolib import domain, generate, llm_params, log_gain
from ..model import Call, Reader, messages
from ..tasks import variant
from . import Container, Ids, Lessons, Record

MERGE_SKILLS = prompts.load("evolib_merge_skills")
MERGE_INSIGHTS = prompts.load("evolib_merge_insights")
COMPARE = prompts.load("evolib_compare")
SIMILAR = 0.8               # порог слияния похожих: косинус строго больше
RATE = 0.5                  # доля нового IG у слитого skill
EMBEDDING = "text-embedding-3-small"    # EmbeddingModel апстрима
NORM_EPS = 1e-8             # знаменатель косинуса embedding_similarity апстрима


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
    return [line.strip() for line in parse.fenced(text, "insights").split("\n") if line.strip().startswith("If ")]


def cosine(a, b):
    """embedding_similarity апстрима."""
    a, b = np.array(a), np.array(b)
    return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + NORM_EPS)


def future_gains(attribution, scores):
    """Future IG: каждой записи, бывшей в промпте лучшей попытки (с повторами), прирост лучшего балла над
    средним по попыткам без этой записи; если таких попыток нет, записи ничего. -> [(id, прирост)]."""
    shown, best = attribution.shown, attribution.best
    out = []
    for rid in shown[best]:
        rest = [score for score, ids in zip(scores, shown) if rid not in ids]
        if rest:
            out.append((rid, log_gain(scores[best], rest)))
    return out


def graded(task, best):
    """Что проверка задачи видит как решение (eval_function апстрима): у hmmt — весь текст решения, у задач стенда —
    ответ FINAL ANSWER."""
    return best.output if variant("evolib", task) == "math" else best.answer


def second_better(judgment):
    """Сравнение решений в пользу второго: «solution 2» в первом блоке ```judgment (is_better_solution апстрима)."""
    return "solution 2" in parse.first_fenced(judgment, "judgment").lower()


class SkillLibrary(Container):
    """skills и insights с общей нумерацией; solutions — лучшее решение каждого вопроса (решателю не видно)."""
    requires = frozenset({IG, BEST_ANSWER, ATTRIBUTION})

    def __init__(self):
        self.ids = Ids()
        self.skills = Lessons("skill", Skill, self.ids)
        self.insights = Lessons("insight", Insight, self.ids)
        self.solutions = {}     # вопрос -> лучшее решение
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
        prompt = COMPARE.fill(question=group.question, a=before.output, b=best.output, **domain(ex.task))
        return generate(ex.model, Call(messages(prompt), llm_params(ex.task), Reader(text=second_better))).output

    def embed(self, ex, texts):
        """embed_strings апстрима: пустая строка — "text"."""
        if not texts:
            return []
        return ex.model.embed([t if t.strip() else "text" for t in texts], EMBEDDING)

    def closest(self, container, vec):
        """Самая похожая запись контейнера (косинус строго больше SIMILAR; при равенстве — первая в порядке
        библиотеки) или None."""
        similar = []
        for r in container.records():
            score = cosine(vec, self.vecs[r.id])
            if score > SIMILAR:
                similar.append((score, r))
        similar.sort(key=lambda pair: pair[0], reverse=True)
        return similar[0][1] if similar else None

    def add(self, container, text, vec, **born):
        rec = container.add(text, **born)
        self.vecs[rec.id] = vec
        self.born[rec.id] = (container, text)

    def remove(self, container, rec):
        container.delete(rec.id)
        del self.vecs[rec.id]

    def merge(self, ex, template, reader, **fields):
        """Слияние старой и новой записи моделью -> слитые записи (reader ответа)."""
        prompt = template.fill(**fields, **domain(ex.task))
        return generate(ex.model, Call(messages(prompt), llm_params(ex.task), reader)).output

    def inherit(self, container, old, merged):
        """Журнал слитых записей: одна слитая наследует журнал старой, старая уходит; несколько — старая остаётся,
        новые делят один новый журнал."""
        if merged != 1:
            return []
        self.remove(container, old)
        return old.outcomes

    def fresh(self, container, text):
        """Текста ещё нет в контейнере: слитый текст, уже лежащий в библиотеке, не добавляется."""
        return text not in {r.text for r in container.records()}

    def add_insight(self, ex, text):
        """add_new_insight: похожего нет — запись добавляется; есть — ближайший сливает с новым модель."""
        vec = self.embed(ex, [condition(text)])[0]
        old = self.closest(self.insights, vec)
        if old is None:
            self.add(self.insights, text, vec, outcomes=[])
            return
        merged = self.merge(ex, MERGE_INSIGHTS, Reader(text=merged_insights),
                            insights=render.merge_input(old.text, text))
        outcomes = self.inherit(self.insights, old, len(merged))
        for new in merged:
            if self.fresh(self.insights, new):
                self.add(self.insights, new, self.embed(ex, [condition(new)])[0], outcomes=outcomes)

    def add_skills(self, ex, blocks, ig):
        """add_new_skills: description всех подзадач — одним запросом эмбеддингов; каждая подзадача по очереди, как
        add_insight; у одной слитой ещё и IG — скользящим средним со старым."""
        vecs = self.embed(ex, [doc for _, doc in blocks])
        for (block, doc), vec in zip(blocks, vecs):
            old = self.closest(self.skills, vec)
            if old is None:
                self.add(self.skills, block, vec, doc=doc, ig=ig, outcomes=[])
                continue
            merged = self.merge(ex, MERGE_SKILLS, Reader(text=parse.subtasks), skills=render.merge_input(old.text, block))
            new_ig = RATE * ig + (1 - RATE) * old.ig if len(merged) == 1 else ig
            outcomes = self.inherit(self.skills, old, len(merged))
            for new_block, new_doc in merged:
                if self.fresh(self.skills, new_block):
                    self.add(self.skills, new_block, self.embed(ex, [new_doc])[0], doc=new_doc, ig=new_ig,
                             outcomes=outcomes)

    def dump(self):
        solutions = [dict(kind="best", id=f"b{i}", question=q, text=s.output, answer=s.answer, score=s.score)
                     for i, (q, s) in enumerate(self.solutions.items(), 1)]
        return self.skills.dump() + self.insights.dump() + solutions
