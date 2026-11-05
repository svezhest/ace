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
SMOKE_CALLS = False   # --smoke-calls: smoke печатает вызовы функций harness/hooks, их аргументы и исключения
RERUN_AT = False   # --rerun-at: в README писателя — python3 tests/rerun.py N --at K (значения на шаге прогона)
FINISH_REVIEW = False   # --finish-review: первый finish — diff всех правок и вывод rerun, второй — конец
RERUN = False   # --rerun: в копии logs/ вида и tests/rerun.py (повтор записанных прогонов на src/)
CHECKED = False   # --checked: в финальных ходах (bash уже нет) правки не применяются
GOAL_TEXT = None  # --goal-text FILE: якорь цели — текст файла после последнего вывода инструмента каждого хода
STAGES = None    # --stages R,K: R bash на чтение; первая правка (или конец R) — ещё K bash на проверку; потом правки не применяются
AUTO_CHECK = False   # --auto-check: каждая применённая правка — pyflakes, smoke и rerun в ответе edit, без bash
RERUN_TOOL = False   # --rerun-tool: rerun — инструмент rerun(change, run) с ожиданием; в копии нет tests/rerun.py
SCRATCH = False      # --scratch: каталог scratch/ копии, куда можно писать (механика исследователя)
TOOLS_DIR = "tests"   # 5.11 --tools-dir: каталог rerun/smoke в копии (tests, tools, __tools)
HIDE_TOOLS = False   # 5.11 --hide-tools: исходников инструментов в копии нет; rerun и smoke — команды
HIDDEN = None        # --hide-tools: каталог инструментов вне копии (work/.tools_<tag>)
GOAL_K = 0        # --goal-k K: когда осталось K вызовов bash, харнесс писателя ставит цель — проверить последние правки

BASH_LIMIT = 25          # вызовов bash; потом — финальные ходы
STEP_BUDGET = 60         # всех вызовов инструментов
FINAL_TURNS = 3
HARD_AT = 54000          # оценка prompt -> финальные ходы
MAX_NO_CALL = 6
SHOW_CONTEXT = 2         # строк вокруг изменённого места в ответе edit
SHOW_MAX = 80
