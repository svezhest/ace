"""Мета-уровень: обёртки над учеником. Обёртка перехватывает свои хуки, остальное (уровни, хуки, снимки) —
у ученика; цикл видит обёртку как ученика.

    Gate(ученик)            правка батча остаётся, только если на val не хуже (решения — в gated, в лог)
    Meta(ученик, author)    итерация = проход: в начале итерации author пишет навык по истории итераций в
                            ученик.skill; в конце прохода — val, запись в историю и откат к лучшей по val
    Hooks(ученик)           хуки по ошибкам инструментов — ace/hooks.py

Навык ученик подставляет в свои промпты обучения сам (skilled): у базового агента MCE — инструкция правки
файлов, у ACE — добавка к системным промптам рефлектора и куратора."""
import copy
from dataclasses import dataclass

from . import prompts
from .learner import swap


def skilled(system, ex):
    """Системный промпт обучения с навыком от мета-уровня; без навыка — как был."""
    skill = getattr(getattr(ex, "learner", None), "skill", "")
    return system + "\n\n" + prompts.text("meta_skill", skill=skill) if skill else system


class Wrapper:
    def __init__(self, inner, name=None):
        self.inner, self.name = inner, name or inner.name

    def __getattr__(self, attr):
        if attr.startswith("__") or attr == "inner":
            raise AttributeError(attr)
        return getattr(self.inner, attr)

    def swap(self, name=None, **levels):
        """Та же обёртка над учеником с заменёнными уровнями."""
        out = copy.deepcopy(self)
        out.inner, out.name = swap(self.inner, **levels), name or self.name
        return out


def correct(results):
    return sum(c for c, _ in results)


def truncated(results):
    return sum(t for _, t in results)


class Gate(Wrapper):
    """Правка на батче принимается, если на val верных не меньше и обрывов не больше, чем до неё. Если память
    не изменилась, проверять нечего."""
    def __init__(self, inner, name=None):
        super().__init__(inner, name)
        self.gated = []

    def on_batch(self, ex, groups):
        before, key = self.inner.snapshot(), self.inner.key()
        self.inner.on_batch(ex, groups)
        if key is not None and self.inner.key() == key:
            return
        after, new = ex.evaluate(), self.inner.snapshot()
        self.inner.restore(before)
        prev = ex.evaluate()
        ok = correct(after) >= correct(prev) and truncated(after) <= truncated(prev)
        if ok:
            self.inner.restore(new)
        self.gated.append(ok)


@dataclass
class Iteration:
    """Итерация меты: навык (text), точность на train за проход и на val, версия памяти ученика после неё."""
    text: str
    train: float
    val: float
    memory: object


def accuracy(results):
    return correct(results) / len(results) if results else 0.0


class Meta(Wrapper):
    """MCE (mce/main.py): итерация = проход по train батчами ученика. Перед первой попыткой прохода
    author(ex, история) пишет навык; train итерации — доля верных за весь проход (среднее по батчам с весом, как
    aggregate_iteration_results). В конце прохода val, итерация — в историю, следующая начинается с лучшей по
    val из уже пройденных (строго больше, при равенстве первая: _find_best_iteration). Нулевой итерации
    (val пустой памяти) нет: апстрим по умолчанию начинает с iter1, а iter0 в выборе не участвует."""
    def __init__(self, inner, author, name=None):
        super().__init__(inner, name)
        self.author, self.history = author, []
        self.fresh, self.right, self.seen = True, 0, 0

    def prompt(self, ex, item, k, memory=None):
        """Первая попытка прохода при обучении открывает итерацию: навык до всего обучения прохода."""
        if ex.training and self.fresh:
            self.inner.skill = self.author(ex, self.history)
            self.fresh = False
        return self.inner.prompt(ex, item, k, memory)

    def on_batch(self, ex, groups):
        self.right += sum(bool(g.episodes[g.chosen].ok) for g in groups)
        self.seen += len(groups)
        self.inner.on_batch(ex, groups)

    def on_pass(self, ex):
        self.inner.on_pass(ex)
        self.history.append(Iteration(self.inner.skill, self.right / self.seen if self.seen else 0.0,
                                      accuracy(ex.evaluate()), self.inner.snapshot()))
        best = self.history[0]
        for h in self.history[1:]:
            if h.val > best.val:
                best = h
        self.inner.restore(best.memory)
        self.fresh, self.right, self.seen = True, 0, 0

    def dump(self):
        return self.inner.dump() + [dict(kind="iterations", id=f"iter{i}", text=h.text, train=h.train, val=h.val)
                                    for i, h in enumerate(self.history, 1)]
