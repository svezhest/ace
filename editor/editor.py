"""Редактор харнесса на 9B (фаза B1): вход — report исследователя, трасс нет; правки — edit(path, old, new).

Два плеча входа:
  obs — наблюдения исследователя (kind, observation, evidence) как есть -> редактор;
  fix — промежуточный шаг (та же 9B, чтение src/, без трасс) превращает наблюдения в варианты исправлений
        словами (propose) -> редактор получает только варианты.
Механика bash (песочница, белый список, обрезка вывода, python3, «/» = корень копии) и транспорт — researcher/fsr.py.
Рабочий каталог сессии: work/<tag>/ = README.md вида без раздела logs/ + копия src/ (edit пишет только сюда)
+ tests/smoke.py (smoke/<bench>.py): прогон src/harness.py на заглушке среды и модели, запуск python3 tests/smoke.py.

python editor.py --bench alf --input a7k5ef --arm obs --seed 1 --tag b1_alf_a7k5ef_obs
python editor.py --bench alf --input a7k5ef --arm fix --seed 1 --tag b1_alf_a7k5ef_fix
python editor.py ... --dry      # напечатать промпты и первые сообщения, без модели

Код — в editorlib/: cfg (пути, виды, лимиты, F = fsr), prompt, schema (инструменты), inputs (report на входе),
work (рабочий каталог, diff), edit, lint (pyflakes), state (Run), tools (вызовы), gate (ворота finish),
phase (финальные ходы), turn (ход), session (run_session), cli (main).
Здесь — общий интерфейс: editor.ИМЯ = имя из модуля-владельца, и чтение, и присваивание (E.BASH_LIMIT = 2,
E.F.chat = заглушка) идут туда, откуда его читают функции.
"""
import sys
import types

sys.dont_write_bytecode = True
from editorlib import cfg as _C, prompt as _P, schema as _SC, inputs as _IN, work as _WK  # noqa: E402
from editorlib import edit as _ED, lint as _LI, state as _R, tools as _TO, gate as _GA  # noqa: E402
from editorlib import phase as _PH, turn as _TU, session as _SE, cli as _CLI  # noqa: E402

F = _C.F
_PARTS = (_C, _P, _SC, _IN, _WK, _ED, _LI, _R, _TO, _GA, _PH, _TU, _SE, _CLI)
_NO = object()


def _owner(k):
    """Модуль editorlib, где определено имя k (импортированные модули не в счёт) -> модуль или None."""
    if k.startswith("__"):
        return None
    for m in _PARTS:
        v = vars(m).get(k, _NO)
        if v is not _NO and not isinstance(v, types.ModuleType):
            return m
    return None


class _Editor(types.ModuleType):
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


sys.modules[__name__].__class__ = _Editor

if __name__ == "__main__":
    _CLI.main()
