"""Редактор харнесса на 9B (фаза B1): вход — report исследователя, трасс нет; правки — edit(path, old, new).

Два плеча входа:
  obs — наблюдения исследователя (kind, observation, evidence) как есть -> редактор;
  fix — промежуточный шаг (та же 9B, чтение src/, без трасс) превращает наблюдения в варианты исправлений
        словами (propose) -> редактор получает только варианты.
Механика bash (песочница, белый список, обрезка вывода, python3, «/» = корень копии) и транспорт — nrhsi.researcher (F).
Рабочий каталог сессии: work/<tag>/ = README.md вида без раздела logs/ + копия src/ (edit пишет только сюда)
+ tests/smoke.py (smoke/<bench>.py): прогон src/harness.py на заглушке среды и модели, запуск python3 tests/smoke.py.
Итог — out/<tag>.diff и out/<tag>.summary.json; logs/, out/, work/ — в каталоге сессий (cfg.HERE, --home).

Модули: cfg (пути, виды, лимиты, F), prompt, schema (инструменты), inputs (report на входе), work (рабочий каталог,
diff), edit, lint (pyflakes), state (Run), tools (вызовы), gate (ворота finish), phase (финальные ходы), turn (ход),
session (run_session), cli (main). nrhsi.editor.ИМЯ = имя из модуля-владельца (nrhsi/facade.py), кроме имён модулей.

  python -m nrhsi.editor --home DIR --rlogs RLOGS --bench alf --view VIEW --input TAG --arm obs --seed 1 --tag t
"""
from .. import facade as _facade
from . import cfg, prompt, schema, inputs, work, edit, lint, state, tools, gate, phase, turn, session, cli

F = cfg.F
PARTS = (cfg, prompt, schema, inputs, work, edit, lint, state, tools, gate, phase, turn, session, cli)
_facade.install(__name__, PARTS)
