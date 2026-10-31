"""Настройки редактора: пути, виды бенчмарков, лимиты сессии; механика bash — исследователя (F = nrhsi.researcher).
Функции других модулей читают значения как C.ИМЯ в момент вызова (editor.ИМЯ = ... меняет их здесь)."""
import os

from .. import researcher as F

# 30.10: механика bash — исследователя (политика final: python3, heredoc), «/» = корень копии.
F.apply_policy("final", {"RUNS_TOOL": False, "SCRATCH": False})   # 31.10: scratch/ — только у исследователя

HERE = None              # каталог сессий: logs/, out/, work/ (--home; editor/editor.py — editor/)
BENCHES = ("alf", "app")
VIEWS = {}               # бенч -> вид узла по умолчанию: README.md, src/ (--view; editor/editor.py — <бенч>/view_v3)
RLOGS = None             # логи сессий исследователя, --input — тег оттуда (--rlogs; editor/editor.py — researcher/logs)
LINT = None              # каталог с pyflakes (pip install --target), первым в sys.path; None — pyflakes окружения
SMOKE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "smoke")   # smoke/<бенч>.py -> tests/smoke.py копии
BENCH = None   # --bench (main)

BASH_LIMIT = 25          # вызовов bash; потом — финальные ходы
STEP_BUDGET = 60         # всех вызовов инструментов
FINAL_TURNS = 3
HARD_AT = 54000          # оценка prompt -> финальные ходы
MAX_NO_CALL = 6
SHOW_CONTEXT = 2         # строк вокруг изменённого места в ответе edit
SHOW_MAX = 80
