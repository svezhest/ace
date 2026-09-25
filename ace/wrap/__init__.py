"""Мета-уровень: обёртки над учеником. Обёртка перехватывает свои хуки, остальное (уровни, хуки, снимки) —
у ученика; цикл видит обёртку как ученика.

    Gate(ученик)            правка батча остаётся, только если на val не хуже (решения — в gated, в лог)
    Meta(ученик, author)    MCE: итерация = проход, в начале итерации author пишет навык по истории итераций в
                            ученик.skill; в конце прохода — val, запись в историю и откат к лучшей по val (mce.py)
    Hooks(ученик)           хуки по ошибкам инструментов (hooks.py)

Навык ученик подставляет в свои промпты обучения сам (skilled): у базового агента MCE — инструкция правки
файлов, у ACE — добавка к системным промптам рефлектора и куратора."""
import copy

from .. import prompts
from ..learner import swap


def skilled(system, ex):
    """Системный промпт обучения с навыком от мета-уровня; без навыка — как был."""
    skill = getattr(getattr(ex, "learner", None), "skill", "")
    return system + "\n\n" + prompts.text("meta_skill", skill=skill) if skill else system


class Wrapper:
    def __init__(self, inner, name=None):
        self.inner, self.name = inner, name or inner.name
        self.check()

    def check(self):
        """Ошибка сборки, если ученик обёртке не подходит."""

    def __getattr__(self, attr):
        if attr.startswith("__") or attr == "inner":
            raise AttributeError(attr)
        return getattr(self.inner, attr)

    def swap(self, name=None, **levels):
        """Та же обёртка над учеником с заменёнными уровнями."""
        out = copy.deepcopy(self)
        out.inner, out.name = swap(self.inner, **levels), name or self.name
        out.check()
        return out


def correct(results):
    return sum(c for c, _ in results)


def truncated(results):
    return sum(t for _, t in results)


class Gate(Wrapper):
    """Правка на батче принимается, если на val верных не меньше и обрывов не больше, чем до неё. Если память
    не изменилась, проверять нечего."""
    needs_val = True
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
