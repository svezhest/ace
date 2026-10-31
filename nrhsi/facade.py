"""Общий интерфейс пакета роли: <модуль>.ИМЯ — имя из модуля-владельца, где оно определено. И чтение, и
присваивание (F.THINKING = True, F.chat = заглушка) идут туда, откуда его читают функции."""
import sys
import types

_NO = object()


def owner(parts, k):
    """Модуль из parts, где определено имя k (импортированные модули не в счёт) -> модуль или None."""
    if k.startswith("__"):
        return None
    for m in parts:
        v = vars(m).get(k, _NO)
        if v is not _NO and not isinstance(v, types.ModuleType):
            return m
    return None


class Facade(types.ModuleType):
    def __getattr__(self, k):
        m = owner(vars(self).get("_PARTS", ()), k)
        if m is None:
            raise AttributeError(f"module {self.__name__!r} has no attribute {k!r}")
        return getattr(m, k)

    def __setattr__(self, k, v):
        m = None if isinstance(v, types.ModuleType) else owner(vars(self).get("_PARTS", ()), k)
        if m is None:
            super().__setattr__(k, v)            # свои имена модуля и подмодули пакета
        else:
            setattr(m, k, v)


def install(name, parts):
    """Модуль name (обычно __name__) становится общим интерфейсом над parts."""
    mod = sys.modules[name]
    mod._PARTS = tuple(parts)
    mod.__class__ = Facade
