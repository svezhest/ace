"""Цикл coding-агента на 9B: общий для исследователя и редактора.

Инструменты: bash только на чтение (песочница sandbox-exec), инструменты роли (report / edit), finish.
Механика сессии (политика `final`, калибровка 29.10): лимит вызовов bash, повтор команды не исполняется,
3 повтора подряд, лимит или край окна -> финал: несколько ходов только с инструментами роли и finish.

Изоляция — профиль sandbox-exec: deny default; исполнять можно только bash и программы из ALLOWED, читать —
только каталог сессии и сами эти программы; записи и сети нет. python3 в песочнице может то же, что bash,
поэтому граница — профиль, а не разбор команд. «/» = корень каталога сессии, как смонтированный образ: аргументы
«/…» и пути python3 переводятся в каталог, в выводе путь каталога -> «/» (песочница та же, это только пути).

Код — в agentlib/: cfg (пути, лимиты, схемы инструментов, строки промпта), sandbox (профиль, «/» = корень, run_bash),
model (chat), state (Run), tools (вызов инструмента), phase (финальные ходы), turn (ход), session (session).
Здесь — общий интерфейс: agent.ИМЯ = имя из модуля-владельца, и чтение, и присваивание (agent.chat = заглушка)
идут туда, откуда его читают функции.
"""
import sys
import types

from agentlib import cfg as _C, sandbox as _SB, model as _MO, state as _R, tools as _TO
from agentlib import phase as _PH, turn as _TU, session as _SE

_PARTS = (_C, _SB, _MO, _R, _TO, _PH, _TU, _SE)
_NO = object()


def _owner(k):
    """Модуль agentlib, где определено имя k (импортированные модули не в счёт) -> модуль или None."""
    if k.startswith("__"):
        return None
    for m in _PARTS:
        v = vars(m).get(k, _NO)
        if v is not _NO and not isinstance(v, types.ModuleType):
            return m
    return None


class _Agent(types.ModuleType):
    def __getattr__(self, k):
        m = _owner(k)
        if m is None:
            raise AttributeError(f"module {self.__name__!r} has no attribute {k!r}")
        return getattr(m, k)

    def __setattr__(self, k, v):
        m = _owner(k)
        if m is None:
            super().__setattr__(k, v)
        else:
            setattr(m, k, v)


sys.modules[__name__].__class__ = _Agent
