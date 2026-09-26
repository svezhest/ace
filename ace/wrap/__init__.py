"""Мета-уровень: обёртки над учеником. Обёртка перехватывает свои хуки, остальное (уровни, хуки) — у ученика; цикл
видит обёртку как ученика.

    Gate(ученик)            правка батча остаётся, только если на val не хуже (решения — в gated, в лог)
    Meta(ученик, author)    MCE: итерация = проход, в начале итерации author пишет навык по истории итераций в
                            ex.skill; в конце прохода — val, запись в историю и откат к лучшей по val (mce.py)
    Iterations(ученик)      MCE апстрима: то же на диске, с мета-агентом Claude SDK (mce.py)
    Evolution(ученик, ...)  GEPA: пул версий с оценками по вопросам val, Парето-выбор родителя (gepa.py)
    Hooks(ученик)           хуки по ошибкам инструментов (hooks.py)

Общее у меты — версия памяти с оценкой на val (loop.Version, loop.evaluated) и сигнал «верен ли ответ» (ex.solved:
проверка задачи, а не вердикт попытки). Своё состояние обёртки (номер кандидата GEPA, книга хуков) входит в снимок,
ключ и версию ученика (state); при случайном показе ключа нет и у обёртки.

Навык меты (ex.skill) подставляют в свои промпты обучения уровни ученика, объявившие skilled (render.skilled):
у базового агента MCE — инструкция правки файлов, у ACE стенда — добавка к системным промптам рефлектора и
куратора."""
import copy

from ..learner import swap
from ..loop import Version, evaluated


class Wrapper:
    """Всё, чего нет у обёртки, берётся у inner (уровни, хуки); inner и служебные dunder — нет, иначе рекурсия при
    deepcopy."""

    def __init__(self, inner, name=None):
        self.inner = inner
        self.name = name or inner.name
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
        out.inner = swap(self.inner, **levels)
        out.name = name or self.name
        out.check()
        return out

    # своё состояние в версии ученика

    def state(self):
        """Своё состояние обёртки в снимке (номер кандидата, книга хуков); None — своего нет."""
        return None

    def restore_state(self, state):
        pass

    def state_key(self):
        """Ключ своего состояния; None — своего нет."""
        return None

    def snapshot(self):
        return self.inner.snapshot(), self.state()

    def restore(self, snapshot):
        memory, state = snapshot
        self.inner.restore(memory)
        self.restore_state(state)

    def version(self):
        return self.inner.version(), self.state_key()

    def key(self):
        """Ключ кэша val: у ученика без ключа (случайный показ) его нет и у обёртки."""
        key = self.inner.key()
        return None if key is None else (key, self.state_key())


def single_meta(wrapper):
    """Итерации по проходам (версия памяти в конце прохода) ведёт одна мета: такая обёртка над другой — ошибка
    сборки."""
    if wrapper.inner.iterates:
        raise ValueError(f"{wrapper.name}: мета над метой — обе ведут итерации по проходам и выбирают версию памяти "
                         "в конце прохода")


class Gate(Wrapper):
    """Правка на батче принимается, если на val верных не меньше и обрывов не больше, чем до неё. Если память
    не изменилась, проверять нечего."""
    needs_val = True

    def __init__(self, inner, name=None):
        super().__init__(inner, name)
        self.gated = []

    def on_batch(self, ex, groups):
        before = self.inner.snapshot()
        version = self.inner.version()
        self.inner.on_batch(ex, groups)
        if self.inner.version() == version:
            return
        after = evaluated(ex, self.inner)
        self.inner.restore(before)
        prev = Version(before, ex.evaluate())
        ok = after.correct >= prev.correct and after.truncated <= prev.truncated
        if ok:
            self.inner.restore(after.memory)
        self.gated.append(ok)
