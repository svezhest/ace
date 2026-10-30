"""Настройки исследователя: пути, адрес модели, лимиты, белый список, политики (POLICIES).
Значения переписывает apply_policy (policy.py); функции других модулей читают их как C.ИМЯ в момент вызова."""
import os


HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # researcher/: каталог fsr.py
LAYOUT = os.path.expanduser("~/Projects/nrhsi/alfworld/view")   # --view
# модель и генерация — только из профиля стенда (stands/<имя>.json, apply_stand в policy.py); до него None
URL = MODEL = TEMP = THINKING = THINK_BUDGET = STAND = None

CTX = 65536
MAX_GEN = None           # max_tokens — из профиля стенда
WARN_AT = 44000          # оценка prompt-токенов: предупреждение (None — нет)
HARD_AT = 54000          # последний ход: только report/finish
CLEAR_AT = 30000         # при такой оценке старые выводы инструментов заменяются заглушкой (или сжатие)
KEEP_RESULTS = 5         # столько последних выводов не трогаем
CLEAR_TO = None          # чистить от старых к новым, пока оценка не опустится до этой границы; None = всё старше KEEP
CLEAR_AT_LEAST = 0       # если освобождается меньше стольких токенов — не чистить вовсе
STUB = ("[output cleared from context to save space ({lines} lines). "
        "Run the command again if you need it.]")   # поля {lines} {chars} {call} {cmd}
NOTES = False            # A2: инструмент note — записи модели, которые не чистятся
COMPACT = False          # A2: вместо заглушек — сжатие: старые сообщения заменяются сводкой, которую пишет модель
POLICY = "base"
VARIANT = "base"
EVIDENCE_MODE = "free"   # A7 (29.10): free — по умолчанию; strict — через --set
TRACE_MODE = "steps"     # не используется в view-раскладке
SNAPSHOT_DIR = None
STEP_BUDGET = 100        # вызовов инструментов
STEP_WARN = 85
REMIND_EVERY = None      # A2: напоминание выключено (было 15)
FINAL_TURNS = 4          # после бюджета/контекста — ходы только с report/finish (S1: 2 -> 4)
BASH_LIMIT = None        # A1: после стольких вызовов bash (все, вкл. повторы и отказы) — финальная фаза; None — нет
FINAL_FIX_TURNS = 0      # A1: пока отклонённый в финале report не исправлен (нет хода с принятым report без отказов),
                         # ходы финала не расходуют FINAL_TURNS (не больше стольких раз), finish откладывается. 0 — как раньше
OUT_CHARS = 8000
CMD_TIMEOUT = 20
MAX_CAPTURE = 200_000
MAX_STDERR = 20_000
LOG_HEAD = 16_000
ALLOWED = {"ls", "cat", "head", "tail", "grep", "wc", "find", "sed", "sort", "uniq", "cut", "echo",
           "awk", "tr", "basename", "dirname", "printf", "nl", "paste", "comm", "diff", "seq", "cd", "test", "[",
           "[[", ":", "read", "true", "false", "break", "continue", "expr", "rev", "column",
           "xargs", "xxd", "od",
           "jq", "pwd", "which", "command"}
WRITE_PROGS = {"tee", "cp", "mv", "rm", "rmdir", "mkdir", "touch", "ln", "dd", "install", "truncate", "chmod", "chown"}
BUILTINS = {"cd", "read", "break", "continue", ":", "[[", "pwd", "command"}
KEYWORDS = {"if", "then", "else", "elif", "fi", "while", "until", "do", "done", "!", "{", "}"}
MAX_DEPTH = 100
MAX_CMD = 8000
FIND_BAD = {"-exec", "-execdir", "-ok", "-okdir", "-delete", "-fprint", "-fprint0", "-fprintf", "-fls"}
ALLOWED_BASE = frozenset(ALLOWED)

# 29.10 (политика final): python, runs, повторы, одно сообщение финала. По умолчанию выключено — поведение прежнее.
PYTHON = False           # python3 в белом списке: python3 -c '...' и python3 - <<'EOF' ... EOF (тело — в stdin)
DIARY = False            # 29.10 (R3'): дневник report — записывать каждое наблюдение сразу, пример в промпте
HYPOTHESES = False       # 29.10 (R1): реестр гипотез hypothesis/verdict (бесплатные), список — после каждого вывода
TAXONOMY = None          # 29.10: "trail" — таксономия ошибок агентов TRAIL (2505.08638, прил. A.11) в «How to work»
CHECKLIST = False        # 29.10: общий чеклист ревьюера агентов в «How to work» (циклы, противоречия, отказы среды, игнор инструкций)
SAY_FIRST = None         # 29.10: перед вызовом bash/runs нужен текст хотя бы из стольких символов (что видела, что проверяет); иначе не исполняется
RUNS_MODE = "bash"       # 29.10: runs — "bash" (программа в bash), "tool" (отдельный инструмент runs(args)), "both"
RUNS_FORMAT = "raw"      # 29.10: runs show/grep — "raw" (строка jsonl как есть) или "text" (поля текстом)
RUNS_TOOL = False        # программа runs (bin/runs) — навигация по logs/; строка промпта про jq -> примеры runs
REPEAT_STOP = None       # повтор команды -> REPEAT_MSG, не исполняется; столько повторов подряд -> финал ("loop")
FINAL_MSG = None         # одно сообщение финала для всех причин (лимит, окно, петля); None — прежнее
REPEAT_MSG = "Don't repeat yourself."
FINAL_MSG_TEXT = ("Limit reached, stop exploring. Write your findings now: one report call per finding, "
                  "then finish.")
BIN = os.path.join(HERE, "bin")                  # runs и python3 -> PY_LINK; в PATH песочницы первым
SITE = os.path.join(HERE, "site")                # sitecustomize.py: «/» = корень вида и для python3
PY_LINK = "/Library/Developer/CommandLineTools/usr/bin/python3"   # /usr/bin/python3 — обёртка xcode-select:
                                                                  # в песочнице не работает

# A2: политики контекста. Значения — в meta лога сессии.
POLICIES = {
    "base": {},                                                     # v3b: 30K, всё старше 5 -> заглушка
    "edge": {"CLEAR_AT": 55000, "CLEAR_TO": 32000, "WARN_AT": None, "HARD_AT": 58000},
    "notes": {"NOTES": True},
    "edge_notes": {"CLEAR_AT": 55000, "CLEAR_TO": 32000, "WARN_AT": None, "HARD_AT": 58000, "NOTES": True},
    "compact": {"COMPACT": True, "CLEAR_AT": 45000, "WARN_AT": None, "HARD_AT": 58000},
    # 29.10: без очистки и сжатия, финал по окну на 52K, лимит bash 40; STEP_* и WARN_AT — как в сессиях A1-40
    "final": {"CLEAR_AT": None, "WARN_AT": None, "HARD_AT": 52000, "BASH_LIMIT": 40, "FINAL_FIX_TURNS": 2,
              "EVIDENCE_MODE": "free", "STEP_BUDGET": 300, "STEP_WARN": 285,
              "PYTHON": True, "RUNS_TOOL": True, "REPEAT_STOP": 3, "FINAL_MSG": FINAL_MSG_TEXT},
}
