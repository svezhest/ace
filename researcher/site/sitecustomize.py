"""«/» = корень вида для python3 в песочнице. Путь «/…» вне вида (NRHSI_ROOT)
открывается из вида, кроме системных путей интерпретатора. Песочница та же; запись и сеть по-прежнему запрещены."""
import builtins
import io
import os

_R = os.environ.get("NRHSI_ROOT")
if _R:
    import sys
    _fw = sys.base_prefix.split(".framework/")[0] + ".framework/"   # stdlib интерпретатора
    _SYS = (_fw, "/dev/", "/usr/share/", "/usr/lib/", "/System/", "/Library/Developer/",
            os.path.dirname(os.path.abspath(__file__)) + "/") + tuple(
        x.rstrip("/") + "/" for x in os.environ.get("NRHSI_SYS", "").split(":") if x)   # наши программы (runs, smoke)

    def _m(p):
        """Абсолютный путь вне каталога -> «каталог/путь», как в смонтированном образе; системные пути — как есть."""
        if hasattr(p, "__fspath__"):
            p = os.fspath(p)
        if not isinstance(p, str) or not p.startswith("/") or p == _R or p.startswith(_R + "/"):
            return p
        if p in ("/", "/."):
            return _R
        if p.startswith(_SYS) or p + "/" in _SYS:
            return p
        return _R + p

    class _W:
        """Вызываемый объект, а не функция: в классе (pathlib._NormalAccessor.stat = os.stat) не связывается с self."""

        def __init__(self, f):
            self.f, self.__name__, self.__doc__ = f, f.__name__, f.__doc__

        def __call__(self, path=None, *a, **k):
            return self.f(*((() if path is None else (_m(path),)) + a), **k)

    import _io
    import posix
    for _n in ("stat", "lstat", "listdir", "scandir", "chdir", "access", "open"):
        _w = _W(getattr(os, _n))
        setattr(os, _n, _w)
        setattr(posix, _n, _w)                       # import (importlib) зовёт posix.stat/listdir напрямую
    builtins.open = io.open = _W(builtins.open)
    _io.open_code = io.open_code = _W(_io.open_code)  # чтение исходника модуля при import
