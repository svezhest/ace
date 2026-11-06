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
INTENT_OPT = False   # --intent-opt (5.11): поля намерения необязательны; зеркало — только если заполнены
ASK_CHANGED = False  # --ask-changed (5.11): после авто-проверки — вопрос про изменившиеся удачные прогоны
TICKET_COVER = False  # --ticket-cover (6.11): к проверке по тикету — счётчики изменённых строк в прогоне тикета
TICKET_RET = False  # --ticket-ret (6.11): к счётчикам ещё и что вернули строки return правки
TICKET_FIRST = False  # --ticket-first (6.11): проверка по тикету — перед lint, smoke и общим rerun
TICKET_LINE = False  # --ticket-line (6.11): факт покрытия одной фразой в строке Failed
TICKET_WHY = False     # --ticket-why (6.11): к факту — почему не действует (перекрытый def, нет ключа), форма длинных строк, факт и при «только тексты»
TICKET_PASSED = False  # --ticket-passed (6.11): к проверке — первый задетый удачный прогон: где расходится и какие изменённые условия в нём сработали
TICKET_ANCHOR = False  # --ticket-anchor (6.11): к значениям — строка лога с ответом модели; у «нет ключа» — что в словаре есть, со значениями
TICKET_VALUES = False  # --ticket-values (6.11): к факту в строке Failed — значения операндов условия на последнем выполнении
TICKET = None       # --ticket (6.11): {change_expected: prompt|control|any, runs}; писатель не видит, проверка после правки
INTENT = False       # --intent (5.11): edit(…, expect_runs, expect); после авто-проверки — сверка с тем, что изменилось
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
