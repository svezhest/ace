"""Исследователь харнесса на 9B: цикл с инструментами bash (только чтение) / report / finish [/ note].
Перенос fsr v3b (scratchpad/reviewer_probe/fsr/fsr.py) на раскладку view/ (README.md, src/, logs/run_N.jsonl,
logs/results.jsonl). Политики контекста (A2) — --policy, см. POLICIES и JOURNAL.md.

python fsr.py --view ~/Projects/nrhsi/alfworld/view --runs 4,8,12 --policy base --seed 1 --tag s1
Вид сессии: views/<name>_<tag>/ = README.md, src/, logs/ (K проваленных + все пройденные, results.jsonl только по ним).
Лог сессии — logs/<name>_<tag>.jsonl.

Код — в fsrlib/: cfg (настройки), prompt, views, sandbox, check, notes, trace, evidence, model, session, policy.
Здесь — общий интерфейс: fsr.ИМЯ = имя из модуля-владельца, и чтение, и присваивание (F.THINKING = True,
fsr.chat = заглушка) идут туда, откуда его читают функции.
"""
import sys
import types

sys.dont_write_bytecode = True
from fsrlib import policy as _policy  # noqa: E402


class _Fsr(types.ModuleType):
    def __getattr__(self, k):
        m = _policy.owner(k)
        if m is None:
            raise AttributeError(f"module {self.__name__!r} has no attribute {k!r}")
        return getattr(m, k)

    def __setattr__(self, k, v):
        m = _policy.owner(k)
        if m is None:
            super().__setattr__(k, v)
        else:
            setattr(m, k, v)


sys.modules[__name__].__class__ = _Fsr

if __name__ == "__main__":
    _policy.L.main()
