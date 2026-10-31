"""Исследователь харнесса на 9B: цикл с инструментами bash (только чтение) / report / finish [/ note и др. по политике].

Вход — вид (--view): README.md, src/, logs/run_N.jsonl, logs/results.jsonl. Сессия видит views/<имя>/ = README.md,
src/, logs/ (K проваленных + все пройденные); лог сессии — logs/<имя>.jsonl; оба — в каталоге сессий (cfg.HERE,
--home). Политики контекста и механики — cfg.POLICIES, --policy, --set KEY=JSON.

Модули: cfg (настройки), prompt, views, sandbox, check, notes, trace, evidence, model, state, context, tools, turn,
phase, nudge, session (сессия и main), policy (политики, профиль стенда).
nrhsi.researcher.ИМЯ = имя из модуля-владельца (nrhsi/facade.py), кроме имён самих модулей.

  python -m nrhsi.researcher --home DIR --view VIEW --k 5 --seed 1 --policy final --tag t
"""
from .. import facade as _facade
from . import policy as _policy

_facade.install(__name__, _policy.PARTS)
