"""Писатель: правит харнесс агента по наблюдениям ревьювера. Сессия одной модели с инструментами bash (чтение копии),
edit(path, old, new) и finish.

Вход: наблюдения (принятые report сессии ревьювера или готовый текст) и, если есть, тикет — ожидание ревьювера
{change_expected, runs, keep}: абзац в конце наблюдения и проверка после каждой правки.
Рабочий каталог сессии: work/<tag>/ = README.md, src/ и logs/ вида + tests/: smoke.py (src/harness.py на заглушке среды
и модели), rerun.py (повтор записанных прогонов на текущем src/), runs.py (чтение логов), orig_src/ (src/ до правок).
Каждая применённая правка сразу проверяется: pyflakes, smoke, rerun всех прогонов и Ok / Failed по тикету — в ответе
edit, bash на это не тратится. После BASH_LIMIT вызовов bash остаётся FINAL_TURNS ходов без bash.
Механика bash (песочница, белый список, обрезка вывода, python3, «/» = корень копии) и транспорт — nrhsi.researcher (F).
Итог — out/<tag>.diff и out/<tag>.summary.json; logs/, out/, work/ — в каталоге сессий (cfg.HERE, --home).

Модули: cfg (пути, виды, лимиты, F), prompt, schema (инструменты), inputs (вход), work (рабочий каталог, diff), edit,
lint (pyflakes), state (Run), tools (вызовы), gate (проверки правки, тикет, ворота finish), phase (финальные ходы),
turn (ход), session (run_session), cli (main). nrhsi.editor.ИМЯ = имя из модуля-владельца (nrhsi/facade.py).
Что было в пакете до 10.11 и убрано (плечи, флаги проб) — docs/REMOVED-1110.md.

  python -m nrhsi.editor --home DIR --bench alf --view VIEW --input-text OBS.txt --ticket TICKET.json --tag t
"""
from .. import facade as _facade
from . import cfg, prompt, schema, inputs, work, edit, lint, state, tools, gate, phase, turn, session, cli

F = cfg.F
PARTS = (cfg, prompt, schema, inputs, work, edit, lint, state, tools, gate, phase, turn, session, cli)
_facade.install(__name__, PARTS)
