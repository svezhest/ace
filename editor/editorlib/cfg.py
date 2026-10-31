"""Настройки редактора: пути, виды бенчмарков, лимиты сессии; механика bash — fsr исследователя (F).
Функции других модулей читают значения как C.ИМЯ в момент вызова (editor.ИМЯ = ... меняет их здесь)."""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # editor/: каталог editor.py
sys.path.insert(0, os.path.expanduser("~/Projects/nrhsi/researcher"))
import fsr as F  # noqa: E402

# 30.10: механика bash — fsr исследователя (политика final: python3, heredoc), «/» = корень копии.
F.apply_policy("final", {"RUNS_TOOL": False})

VIEWS = {"alf": os.path.expanduser("~/Projects/nrhsi/alfworld/view"),
         "app": os.path.expanduser("~/Projects/nrhsi/appworld/view")}
RLOGS = os.path.expanduser("~/Projects/nrhsi/researcher/logs")
BENCH = None   # --bench (main)

BASH_LIMIT = 25          # вызовов bash; потом — финальные ходы
STEP_BUDGET = 60         # всех вызовов инструментов
FINAL_TURNS = 3
HARD_AT = 54000          # оценка prompt -> финальные ходы
MAX_NO_CALL = 6
SHOW_CONTEXT = 2         # строк вокруг изменённого места в ответе edit
SHOW_MAX = 80
