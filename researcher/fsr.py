"""Исследователь харнесса на 9B: цикл с инструментами bash (только чтение) / report / finish [/ note].
Перенос fsr v3b (scratchpad/reviewer_probe/fsr/fsr.py) на раскладку view/ (README.md, src/, logs/run_N.jsonl,
logs/results.jsonl). Политики контекста (A2) — --policy, см. POLICIES и JOURNAL.md.

python fsr.py --view ~/Projects/nrhsi/alfworld/view --runs 4,8,12 --policy base --seed 1 --tag s1
Вид сессии: views/<name>_<tag>/ = README.md, src/, logs/ (K проваленных + все пройденные, results.jsonl только по ним).
Лог сессии — logs/<name>_<tag>.jsonl.
"""
import argparse
import atexit
import glob
import json
import os
import random
import re
import selectors
import shlex
import shutil
import signal
import stat
import subprocess
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
LAYOUT = os.path.expanduser("~/Projects/nrhsi/alfworld/view")   # --view
URL = "http://127.0.0.1:8089/v1/chat/completions"
THINK_URL = "http://127.0.0.1:8081/v1/chat/completions"   # 29.10: второй шлюз без GATEWAY_THINKING=off
MODEL = "ornith15-9b"

CTX = 65536
MAX_GEN = 4096
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
           "jq"}
WRITE_PROGS = {"tee", "cp", "mv", "rm", "rmdir", "mkdir", "touch", "ln", "dd", "install", "truncate", "chmod", "chown"}
BUILTINS = {"cd", "read", "break", "continue", ":", "[["}
KEYWORDS = {"if", "then", "else", "elif", "fi", "while", "until", "do", "done", "!", "{", "}"}
MAX_DEPTH = 100
MAX_CMD = 8000
FIND_BAD = {"-exec", "-execdir", "-ok", "-okdir", "-delete", "-fprint", "-fprint0", "-fprintf", "-fls"}
ALLOWED_BASE = frozenset(ALLOWED)

# 29.10 (политика final): python, runs, повторы, одно сообщение финала. По умолчанию выключено — поведение прежнее.
PYTHON = False           # python3 в белом списке: python3 -c '...' и python3 - <<'EOF' ... EOF (тело — в stdin)
THINKING = False         # 29.10: enable_thinking через THINK_URL; рассуждение — в лог (reasoning), в историю не идёт
THINK_BUDGET = None      # thinking_budget шлюза (токенов рассуждения на ход); None — без ограничения
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

EX_EV = '["logs/run_N.jsonl:40-44", "src/FILE:12-30"]'   # N, FILE — заполнители, не настоящие пути
# A7: EVIDENCE_MODE="free" (--set EVIDENCE_MODE='"free"') — evidence в свободной форме (цитата с путём, path:line,
# путь); проверяется только существование пути, номера строк и цитаты — нет. Меняются только описания evidence
# (строка report в промпте, схема инструмента, пример report, подсказка отказа); strict — байт в байт как было.
EX_EV_FREE = '["logs/run_N.jsonl: <short quote>", "src/FILE:12-30"]'
EV_STRICT_SYS = ("evidence is a list of references \"path:line\" or \"path:start-end\"; the line numbers are those of "
                 "the file itself, as grep -n PATTERN FILE or sed -n 'a,bp' FILE print them (output passed through "
                 "another program has its own numbering), for example EX_EV. A file of up to 80 lines can be cited by "
                 "its path alone. References are checked.")
EV_FREE_SYS = ("evidence is a list of what supports the finding, in free form: a short quote copied from a file "
               "together with its path, \"path:line\" or \"path:start-end\", or a path alone, for example EX_EV. "
               "Paths are checked to exist; line numbers and quotes are not checked.")
EV_FREE_DESC = ("What supports the finding, in free form: a short quote with the path of its file "
                "(e.g. logs/run_N.jsonl: <short quote>), 'path:line', 'path:start-end' or a path; paths are "
                "checked to exist")


def ex_ev():
    return EX_EV_FREE if EVIDENCE_MODE == "free" else EX_EV

CTX_LINE = {
    "stub": ("Outputs of older commands are cleared from your context as you go, and the session ends after "
             "STEP_BUDGET tool calls. Recorded findings are kept."),
    "notes": ("Outputs of older commands are cleared from your context as you go; what you write yourself (your "
              "messages, notes and reports) stays. When an output shows something you will need later, write it "
              "down with note: the fact and the path:line it comes from. The session ends after STEP_BUDGET tool "
              "calls. Recorded findings are kept."),
    "compact": ("When your context fills up, older messages are removed and replaced by a summary you write "
                "yourself at that moment; the session ends after STEP_BUDGET tool calls. Recorded findings are kept."),
    # 29.10: CLEAR_AT=None и без сжатия (политика final) — прежняя строка «outputs ... are cleared» была бы неправдой
    "none": ("The context is not cleared, and the session ends after STEP_BUDGET tool calls. Recorded findings "
             "are kept."),
}

SYSTEM_T = """You are a research agent working in a read-only copy of a repository: the source code of an AI agent's harness (its prompts and the code that runs it) and the logs of the agent's runs on tasks. Some runs passed and some failed.

Your job: find the weaknesses of the harness — in its prompts or its code — that make runs fail, and show how each one leads to failure. Look for concrete problems in individual failed runs, behaviour patterns that recur across runs, and meta-observations about how the runs unfold as a whole. Name the part of the harness responsible whenever you can tell. Every finding must rest on lines you have actually read in the files.

# Tools
- bash(command): a read-only shell in the working directory. Programs: PROGRAMS. Pipes, ';', '&&', '||', $(...), for/while loops and if work. Nothing can be written (no files, no /tmp). Output longer than OUT_CHARS characters is truncated, so read big files in parts (sed -n '40,90p' FILE, head, tail) and search with grep -n.
- The shell is bash 3.2 with macOS/BSD utilities: GNU-only options are missing (use grep -E, not grep -P; no find -printf).
- report(kind, observation, evidence): record one finding. kind is "problem", "pattern" or "meta". evidence is a list of references "path:line" or "path:start-end"; the line numbers are those of the file itself, as grep -n PATTERN FILE or sed -n 'a,bp' FILE print them (output passed through another program has its own numbering), for example EX_EV. A file of up to 80 lines can be cited by its path alone. References are checked.
NOTE_TOOL- finish(): end the investigation.

# How to work
- README.md describes the layout.
- Work like an engineer debugging a system: look around, form a hypothesis, check it against the files, record it, continue.
- Record each finding with report as soon as you have its supporting lines. CTX_LINE
- Targeted commands (grep -n, sed -n ranges) work better than printing many whole files at once.
- For .json and .jsonl files jq is often easier than grep: sed -n 'Np' FILE | jq . shows line N of a JSONL file as readable JSON, and N is the line number to cite.
- Call finish when you are done."""

NOTE_TOOL_LINE = ("- note(text): write down something you will need later — a fact with the path:line it comes "
                  "from, a hypothesis, what you have checked. Notes stay in your context.\n")

FIRST_USER = ("Investigate the failed runs in this repository and report what in the harness makes them fail. "
              "Call finish when you are done.")

COMPACT_REQ = ("Your context is nearly full. All messages before this one will now be removed from your context, "
               "except the system prompt, the first instruction and your last few tool calls, and replaced by what "
               "you write in your next reply. Write down everything from your work so far that you will still "
               "need: facts you established, each with the exact path:line it comes from; hypotheses and whether "
               "you checked them; files and runs you have read and what is left; what you planned to do next. "
               "Findings already recorded with report are kept and will be listed for you. Reply with text only, "
               "no tool calls.")


JQ_LINE = ("- For .json and .jsonl files jq is often easier than grep: sed -n 'Np' FILE | jq . shows line N of a JSONL "
           "file as readable JSON, and N is the line number to cite.")
RUNS_LINE = """- runs (a program in bash) reads the run logs message by message:
    runs                          list runs: result, reason, size
    runs show N 40-45             messages 40-45 (= lines 40-45 of logs/run_N.jsonl)
    runs show N --tail 6          the last 6 messages
    runs grep -i "error" N M      matches in runs N and M, with message numbers"""
RUNS_TOOL_LINE = """- runs(args): reads the run logs message by message; args as on a command line:
    runs(args="")                       list runs: result, reason, size
    runs(args="show N 40-45")           messages 40-45 (= lines 40-45 of logs/run_N.jsonl)
    runs(args="show N --tail 6")        the last 6 messages
    runs(args="grep -i error N M")      matches in runs N and M, with message numbers
  It counts as a bash call."""
RUNS_BOTH_NOTE = "\n  The same program is also available inside bash as runs, e.g. for r in 4 7; do runs show $r --tail 4; done."
RUNS_TOOL_EXAMPLE = """- An example of how a session can start:
    bash: cat README.md
    >> (the layout)
    bash: cat -n src/harness.py
    >> (the code)
    ... the prompts and other files you need
    runs: ""
    >> (runs with their results)
    runs: "show N 1-2"
    >> (the first messages, trimmed) -- the prompt from src/, as expected
    runs: "show N --tail 6"
    >> (how the run ended)
    ... then find where it went wrong, compare with a passed run, report."""
RUNS_EXAMPLE = """- An example of how a session can start:
    bash: cat README.md
    >> (the layout)
    bash: cat -n src/harness.py
    >> (the code)
    ... the prompts and other files you need
    bash: runs
    >> (runs with their results)
    bash: runs show N 1-2
    >> (the first messages, trimmed) -- the prompt from src/, as expected
    bash: runs show N --tail 6
    >> (how the run ended)
    ... then find where it went wrong, compare with a passed run, report."""
BASH_TAIL = "so read big files in parts (sed -n '40,90p' FILE, head, tail) and search with grep -n."
BASH_TAIL_RUNS = "so read big files in parts (sed -n '40,90p' FILE, head, tail) and search with grep -n; read the logs with runs."
TARGETED = "- Targeted commands (grep -n, sed -n ranges) work better than printing many whole files at once."
TARGETED_RUNS = "- Targeted commands (grep -n, sed -n ranges, runs show N A-B) work better than printing many whole files at once."
BSD_LINE = "- The shell is bash 3.2 with macOS/BSD utilities: GNU-only options are missing (use grep -E, not grep -P; no find -printf)."
PYTHON_LINE = "- python3 is available (standard library; no network, nothing can be written)."

RECORD_LINE = "- Record each finding with report as soon as you have its supporting lines."
DIARY_LINE = """- Keep a diary of findings with report: whenever an output shows you something about why runs fail, record it right away, in the same reply as your next command. Small and partial findings count too; a later report can refine an earlier one. Most of your replies should contain a report.
- The rhythm of a diary (placeholders, not real content):
    bash: <command>
    >> (output that shows something about a failure)
    report(kind="problem", observation="<what you saw and how it leads to the failure>", evidence=["<path>:<lines>"])
    bash: <next command>
    >> (nothing new)
    bash: <next command>
    >> (more about the same problem)
    report(kind="problem", observation="<the earlier finding, made more precise>", evidence=["<path>:<lines>"])"""
HYP_LINE = """- hypothesis(claim, confirms_if, refutes_if): before checking an idea, state it and what output would confirm or refute it. It returns an id; your hypotheses and their verdicts are listed after each command output.
- verdict(id, result, why): after the check; result is held, refuted or unclear. A refuted claim is not a finding."""
TRAIL_LINE = """- A taxonomy of agent errors (TRAIL, 2025) to name what you see in the runs; the harness weakness is what lets such an error happen or go unnoticed:
    Reasoning: hallucinations (language-only; tool-related: invented tool outputs or capabilities); information processing (poor information retrieval; tool output misinterpretation); decision making (incorrect problem identification; tool selection errors); output generation (formatting errors; instruction non-compliance).
    System execution: configuration (tool definition issues; environment setup errors); API issues (rate limiting, authentication, service errors, resource not found); resource management (resource exhaustion; timeout issues).
    Planning and coordination: context management (context handling failures: window overflow, lost state; resource abuse: excessive tool calls); task management (goal deviation; task orchestration: subtask coordination, progress monitoring).
    Domain-specific errors."""
CHECK_LINE = ("- When reviewing runs, look for loops and repeated actions, contradictions (between what the agent says, "
              "what the environment returns and what the prompt says), errors the agent does not react to, and "
              "instructions it does not follow.")
SAY_LINE = "- Before each command, write in a sentence or two what you saw in the last output and what the command will check."
SAY_MSG = "Not run. First write what you saw in the last output and what this command will check, then call it again."
LIMIT_LINE = ("bash can be called N times; after that only report and finish remain, for a few turns, and the "
              "session ends")   # A1: вместо «the session ends after STEP_BUDGET tool calls»


def build_system():
    ctx = "compact" if COMPACT else "notes" if NOTES else "none" if CLEAR_AT is None else "stub"
    s = SYSTEM_T.replace("NOTE_TOOL", NOTE_TOOL_LINE if NOTES else "").replace("CTX_LINE", CTX_LINE[ctx])
    if EVIDENCE_MODE == "free":
        assert EV_STRICT_SYS in s
        s = s.replace(EV_STRICT_SYS, EV_FREE_SYS)
    if RUNS_TOOL:     # 29.10 v2: runs — в Tools, пример начала сессии вместо строки про jq
        assert JQ_LINE in s and BASH_TAIL in s and TARGETED in s and BSD_LINE in s
        if RUNS_MODE == "bash":
            s = (s.replace(JQ_LINE, RUNS_EXAMPLE).replace(BASH_TAIL, BASH_TAIL_RUNS).replace(TARGETED, TARGETED_RUNS)
                 .replace(BSD_LINE, RUNS_LINE + "\n" + BSD_LINE))
        else:         # tool / both: runs(args) — отдельный инструмент; both — ещё и программа в bash
            line = RUNS_TOOL_LINE + (RUNS_BOTH_NOTE if RUNS_MODE == "both" else "")
            s = (s.replace(JQ_LINE, RUNS_TOOL_EXAMPLE).replace(BASH_TAIL, BASH_TAIL_RUNS)
                 .replace(TARGETED, TARGETED_RUNS.replace("runs show N A-B", "runs show N A-B"))
                 .replace(BSD_LINE, BSD_LINE + "\n" + line))
    if DIARY:
        assert RECORD_LINE + " " in s
        s = s.replace(RECORD_LINE + " ", DIARY_LINE + "\n- ")
    if HYPOTHESES:
        fl = "- finish(): end the investigation."
        assert fl in s
        s = s.replace(fl, HYP_LINE + "\n" + fl)
    if TAXONOMY == "trail":
        w_ = "- Work like an engineer debugging a system"
        i_ = s.index(w_)
        j_ = s.index("\n", i_)
        s = s[:j_ + 1] + TRAIL_LINE + "\n" + s[j_ + 1:]
    if CHECKLIST:
        w_ = "- Work like an engineer debugging a system"
        i_ = s.index(w_)
        j_ = s.index("\n", i_)
        s = s[:j_ + 1] + CHECK_LINE + "\n" + s[j_ + 1:]
    if SAY_FIRST:
        w_ = "- Work like an engineer debugging a system"
        i_ = s.index(w_)
        j_ = s.index("\n", i_)
        s = s[:j_ + 1] + SAY_LINE + "\n" + s[j_ + 1:]
    if PYTHON:
        assert BSD_LINE in s
        s = s.replace(BSD_LINE, BSD_LINE + "\n" + PYTHON_LINE)
    progs = sorted(ALLOWED - ({"runs"} if RUNS_TOOL and RUNS_MODE == "tool" else set()))
    return (s.replace("PROGRAMS", ", ".join(progs)).replace("OUT_CHARS", str(OUT_CHARS))
            .replace("the session ends after STEP_BUDGET tool calls", LIMIT_LINE.replace("N", str(BASH_LIMIT))
                     if BASH_LIMIT else "the session ends after STEP_BUDGET tool calls")
            .replace("STEP_BUDGET", str(STEP_BUDGET)).replace("EX_EV", ex_ev()))


SYSTEM = build_system()


def build_report_example():
    return f'report(kind="pattern", observation="...", evidence={ex_ev()})'


REPORT_EXAMPLE = build_report_example()


def build_tools():
    t = [
        {"type": "function", "function": {
            "name": "bash", "description": "Run a read-only shell command in the working directory. Pipes, ';', '&&', '||', "
            "$(...), for/while loops and if work; nothing can be written. Long output is truncated: use grep -n, sed -n 'a,bp', head, tail.",
            "parameters": {"type": "object", "properties": {"command": {"type": "string", "description": "The command line"}},
                           "required": ["command"]}}},
        {"type": "function", "function": {
            "name": "report", "description": "Record one finding with evidence. Call it as soon as a finding is supported; "
            "several report calls in one reply are fine.",
            "parameters": {"type": "object", "properties": {
                "kind": {"type": "string", "enum": ["problem", "pattern", "meta"]},
                "observation": {"type": "string", "description": "What you found and why it matters"},
                "evidence": {"type": "array", "items": {"type": "string"},
                             "description": "References 'path:line' or 'path:start-end', e.g. logs/run_N.jsonl:40-44; "
                                            "a file of up to 80 lines may be cited by its path alone"}},
                "required": ["kind", "observation", "evidence"]}}},
        {"type": "function", "function": {
            "name": "finish", "description": "End the investigation.",
            "parameters": {"type": "object", "properties": {}}}},
    ]
    if EVIDENCE_MODE == "free":
        t[1]["function"]["parameters"]["properties"]["evidence"]["description"] = EV_FREE_DESC
    if HYPOTHESES:
        t[-1:-1] = [
            {"type": "function", "function": {
                "name": "hypothesis", "description": "State an idea before checking it: the claim and what output "
                "would confirm or refute it. Returns an id. Free: does not count as a bash call.",
                "parameters": {"type": "object", "properties": {
                    "claim": {"type": "string"}, "confirms_if": {"type": "string"}, "refutes_if": {"type": "string"}},
                    "required": ["claim", "confirms_if", "refutes_if"]}}},
            {"type": "function", "function": {
                "name": "verdict", "description": "The result of checking a hypothesis. Free: does not count as a bash call.",
                "parameters": {"type": "object", "properties": {
                    "id": {"type": "string", "description": "e.g. H1"},
                    "result": {"type": "string", "enum": ["held", "refuted", "unclear"]},
                    "why": {"type": "string"}}, "required": ["id", "result", "why"]}}}]
    if RUNS_TOOL and RUNS_MODE in ("tool", "both"):
        t.insert(1, {"type": "function", "function": {
            "name": "runs", "description": "Read the run logs message by message. args as on a command line: '' lists "
            "runs; 'show N 40-45', 'show N --tail 6', 'grep -i PATTERN N M'; 'help' for all options.",
            "parameters": {"type": "object", "properties": {"args": {"type": "string", "description": "The arguments"}},
                           "required": ["args"]}}})
    if NOTES:
        t.insert(1, {"type": "function", "function": {
            "name": "note", "description": "Write down something you will need later: a fact with the path:line it "
            "comes from, a hypothesis, what you have checked. Notes stay in your context; command outputs do not.",
            "parameters": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}}})
    return t


TOOLS = build_tools()
FINAL_TOOLS = [x for x in TOOLS if x["function"]["name"] in ("report", "finish")]


def apply_policy(name, overrides=None):
    global SYSTEM, TOOLS, FINAL_TOOLS, POLICY, VARIANT, REPORT_EXAMPLE, ALLOWED
    g = globals()
    for k, v in {**POLICIES[name], **(overrides or {})}.items():
        assert k in g, k
        g[k] = v
    assert EVIDENCE_MODE in ("strict", "free"), EVIDENCE_MODE
    ALLOWED = set(ALLOWED_BASE) | ({"python3"} if PYTHON else set()) | ({"runs"} if RUNS_TOOL else set())
    POLICY = VARIANT = name
    REPORT_EXAMPLE = build_report_example()
    SYSTEM = build_system()
    TOOLS = build_tools()
    FINAL_TOOLS = [x for x in TOOLS if x["function"]["name"] in ("report", "finish")]


# ---------------------------------------------------------------- виды

def results_rows():
    return [json.loads(l) for l in open(f"{LAYOUT}/logs/results.jsonl") if l.strip()]


def all_tids():
    return [r["run"] for r in results_rows() if not r["ok"]]


def select(mode, k, seed, runs=None):
    """-> (проваленные run в виде, sel). runs — явный список; иначе k случайных проваленных с seed."""
    failed = all_tids()
    if runs:
        assert all(r in failed for r in runs), (runs, failed)
        return sorted(runs), {"explicit": True}
    rng = random.Random(seed)
    return sorted(rng.sample(failed, k)), {"rand_seed": seed}


def _pid_alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def claim_view(name):
    """v3c: имя вида на сессию. Владелец вида — pid в views/.<имя>.lock (вне вида). Вид живой сессии не трогаем:
    занято живым процессом -> имя с суффиксом _p<pid>. -> (имя, путь lock-файла)."""
    os.makedirs(f"{HERE}/views", exist_ok=True)
    for cand in (name, f"{name}_p{os.getpid()}"):
        lock = f"{HERE}/views/.{cand}.lock"
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                with open(lock) as f:
                    owner = int(f.read().strip() or 0)
            except (OSError, ValueError):
                owner = 0
            if owner and owner != os.getpid() and _pid_alive(owner):
                continue                                # вид живой сессии
            fd = os.open(lock, os.O_WRONLY | os.O_TRUNC)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return cand, lock
    raise RuntimeError(f"view {name} is in use")


def release_view(lock):
    try:
        with open(lock) as f:
            mine = f.read().strip() == str(os.getpid())
        if mine:
            os.unlink(lock)
    except OSError:
        pass



def build_view(name, tids):
    """Вид views/<name>: README.md, src/, logs/ = выбранные проваленные run + все пройденные; results.jsonl — их строки."""
    v = f"{HERE}/views/{name}"
    if os.path.lexists(v):
        shutil.rmtree(v)
    _link(f"{LAYOUT}/README.md", f"{v}/README.md")
    _link(f"{LAYOUT}/src", f"{v}/src")
    for p in glob.glob(f"{v}/src/**/__pycache__", recursive=True):
        shutil.rmtree(p)
    rows = [r for r in results_rows() if r["ok"] or r["run"] in tids]
    os.makedirs(f"{v}/logs", exist_ok=True)
    for r in rows:
        _link(f"{LAYOUT}/logs/run_{r['run']}.jsonl", f"{v}/logs/run_{r['run']}.jsonl")
    with open(f"{v}/logs/results.jsonl", "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    return os.path.realpath(v)


def _inside(path, base):
    base = os.path.realpath(base)
    return path == base or path.startswith(base + os.sep)


def _link(src, dst, base=None):
    """Жёсткие ссылки src -> dst. v3c: только обычные файлы, симлинки не разыменовываются и пропускаются
    (и файлы, и каталоги), realpath(src) обязан лежать внутри base (по умолчанию LAYOUT)."""
    base = LAYOUT if base is None else base
    st = os.lstat(src)
    if stat.S_ISLNK(st.st_mode):
        return
    if not _inside(os.path.realpath(src), base):        # путь через симлинк-каталог наружу
        raise ValueError(f"_link: {src} is outside {base}")
    if not stat.S_ISDIR(st.st_mode):
        if stat.S_ISREG(st.st_mode):
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            os.link(src, dst, follow_symlinks=False)
        return
    for root, _, files in os.walk(src):              # followlinks=False: в симлинк-каталоги не заходим
        r = os.path.join(dst, os.path.relpath(root, src))
        os.makedirs(r, exist_ok=True)
        for f in files:
            s = os.path.join(root, f)
            if stat.S_ISREG(os.lstat(s).st_mode) and _inside(os.path.realpath(s), base):
                os.link(s, os.path.join(r, f), follow_symlinks=False)


# ---------------------------------------------------------------- песочница

_PROFILES = []          # профили этого процесса: удаляются при выходе


@atexit.register
def _rm_profiles():
    for p in _PROFILES:
        try:
            os.unlink(p)
        except OSError:
            pass


def exec_programs():
    """Пути программ белого списка (PATH=/usr/bin:/bin) и /bin/bash: только их разрешает process-exec.
    Встроенные (cd, read) — не программы: /usr/bin/cd, /usr/bin/read — обёртки на /bin/sh, их не берём."""
    out = {"/bin/bash"}
    for p in ALLOWED - BUILTINS - {"python3", "runs"}:
        for d in ("/usr/bin", "/bin"):
            f = f"{d}/{p}"
            if os.path.isfile(f) and os.access(f, os.X_OK):
                out.add(f)
    if {"python3", "runs"} & ALLOWED:
        py = py_paths()
        out |= {py["launcher"], py["app"]}
    if "runs" in ALLOWED:
        out.add(os.path.join(BIN, "runs"))
    return sorted(out)


def py_paths():
    """29.10: python3 для песочницы. bin/python3 -> PY_LINK -> .../Python3.framework/Versions/X/bin/python3.X —
    запускалка, она порождает Resources/Python.app/Contents/MacOS/Python. -> пути для профиля."""
    launcher = os.path.realpath(PY_LINK)
    ver = os.path.dirname(os.path.dirname(launcher))                 # .../Python3.framework/Versions/3.9
    fw = os.path.dirname(os.path.dirname(ver))                       # .../Python3.framework
    app = os.path.join(ver, "Resources/Python.app/Contents/MacOS/Python")
    assert fw.endswith(".framework") and os.path.isfile(app), (launcher, app)
    return {"launcher": launcher, "app": app, "framework": fw, "link": PY_LINK}


def _ancestors(p):
    out = []
    while p not in ("/", ""):
        out.append(p)
        p = os.path.dirname(p)
    return out


def profile_text(root):
    """v3c: (deny default) и явные allow; обоснование каждого — journal.md, «Механика v3c».
    exec — только bash и программы белого списка; чтение — вид, эти программы, локаль, /dev/null|urandom|fd/N;
    «/» (file-read-data) — без него dyld роняет процесс (SIGABRT); sysctl-read — dyld/libc при старте."""
    lit = lambda ps: " ".join(f'(literal "{p}")' for p in ps)      # noqa: E731
    progs = exec_programs()
    return f"""(version 1)
(deny default)
(allow process-fork)
(allow process-exec {lit(progs)})
(allow file-read* {lit(progs)})
(allow file-read-data (literal "/"))
(allow file-read* (subpath "/usr/share/locale"))
(allow sysctl-read)
(allow file-read* (literal "/dev/null") (literal "/dev/urandom") (regex #"^/dev/fd/[0-9]+$"))
(allow file-write-data (literal "/dev/null"))
(allow file-read* (subpath "{root}"))
(allow file-read-metadata (literal "{os.path.dirname(root)}"))
""" + _py_profile()


def _py_profile():
    """29.10 (PYTHON / RUNS_TOOL): чтение stdlib (каталог фреймворка), bin/ и цепочки ссылок до запускалки;
    метаданные предков — для realpath запускалки. Запись и сеть — как у всех: deny default."""
    if not {"python3", "runs"} & ALLOWED:
        return ""
    py = py_paths()
    lit = lambda ps: " ".join(f'(literal "{p}")' for p in ps)      # noqa: E731
    reads = [BIN, os.path.join(BIN, "python3"), py["link"], os.path.dirname(py["link"])]
    if "runs" in ALLOWED:
        reads.append(os.path.join(BIN, "runs"))
    meta = ["/"] + sorted({a for p in (BIN, py["link"], py["launcher"]) for a in _ancestors(os.path.dirname(p))})
    return (f'(allow file-read* {lit(reads)} (subpath "{py["framework"]}"))\n'
            f"(allow file-read-metadata {lit(meta)})\n")


def sandbox_profile(root, name=None):
    """Профиль sandbox-exec для вида root. v3c: имя уникально на процесс (pid), запись атомарная, файл
    удаляется при выходе — параллельные сессии/тесты не перетирают чужой профиль."""
    os.makedirs(f"{HERE}/views", exist_ok=True)
    p = os.path.abspath(f"{HERE}/views/.sb_{name or os.path.basename(root)}_{os.getpid()}.sb")
    tmp = p + ".tmp"
    with open(tmp, "w") as f:
        f.write(profile_text(root))
    os.replace(tmp, p)
    if p not in _PROFILES:
        _PROFILES.append(p)
    return p


class _Deny(Exception):
    pass


READONLY_MSG = ("the directory is read-only and nothing can be written (no files, no /tmp); "
                "print results to stdout instead and narrow them with grep, head or sed -n")
HEREDOC_PY_MSG = ("here-documents (<<) work only as a whole command python3 - <<'EOF' ... EOF (a pipe like | head "
                  "may follow <<'EOF' on its first line); otherwise pass text with echo or printf through a pipe")
HEREDOC_RE = re.compile(r"\s*python3(?:[ \t]+-)?[ \t]*<<(-?)[ \t]*(['\"]?)([A-Za-z_]\w*)\2([^\n]*)\n")


def split_heredoc(cmd):
    """29.10 (PYTHON): python3 [-] <<[-]'EOF' [| ...]\n тело\nEOF -> ("python3 -[ | ...]", тело) или None.
    Тело идёт в stdin как есть (без подстановок, как при 'EOF'); после строки-ограничителя — ничего.
    Нет ограничителя — тело до конца (bash делает так же)."""
    m = HEREDOC_RE.match(cmd)
    if not m:
        return None
    tabs, word = m.group(1) == "-", m.group(3)
    lines = cmd[m.end():].split("\n")
    body = []
    for i, ln in enumerate(lines):
        x = ln.lstrip("\t") if tabs else ln
        if x.rstrip() == word:
            if "\n".join(lines[i + 1:]).strip():
                return None
            break
        body.append(x)
    return "python3 -" + m.group(4), "\n".join(body) + "\n"


NO_SUBST_MSG = ("command substitution inside ${...} or $((...)) is not supported; "
                "assign it to a variable first: v=$(...)")


def _cmd_pos(cur):
    """Начало простой команды: до сих пор в ней только ключевые слова (if, while, do, ! ...)."""
    return all(w in KEYWORDS for w in "".join(cur).split())


def _arith_end(s, i):
    """s[i:] начинается с '((' или '$((': -> индекс после '))'. Подстановку команды внутри не пускаем:
    v2 пропускал тело $((...)) не глядя, и $(( $(prog) )) обходил белый список."""
    j = s.find("))", i)
    if j < 0:
        raise _Deny("unbalanced $((")
    if "$(" in s[i + 2:j] or "`" in s[i + 2:j]:
        raise _Deny(NO_SUBST_MSG)
    return j + 2


def _scan(s, i, close, segs, meta=None, pipeamp=None, depth=0):
    """Разбор командной строки с кавычками. Режет на простые команды (segs); подстановки $(...), `...` и <(...)
    разбираются рекурсивно как отдельные команды, на их месте остаётся слово X. meta (v3): на каждую простую
    команду {piped: вход из пайпа, procsub: есть <(...), redir_in: есть '<'}. -> индекс после close.
    v3c: вложенность не глубже MAX_DEPTH (иначе RecursionError ронял харнесс)."""
    if depth > MAX_DEPTH:
        raise _Deny(f"command substitutions are nested more than {MAX_DEPTH} levels deep")
    cur = []
    st = {"piped": False, "procsub": False, "redir_in": False}
    dbl = False                                         # внутри [[ ... ]]: < > && || ( ) | — операторы теста

    def cut(piped_next=False):
        segs.append("".join(cur))
        if meta is not None:
            meta.append(dict(st))
        cur.clear()
        st.update(piped=piped_next, procsub=False, redir_in=False)

    while i < len(s):
        c = s[i]
        if close and not dbl and s.startswith(close, i):
            cut()
            return i + len(close)
        if c == "\\":
            cur.append(s[i:i + 2])
            i += 2
        elif c == "'":
            j = s.find("'", i + 1)
            if j < 0:
                raise _Deny("unbalanced quotes")
            cur.append(s[i:j + 1])
            i = j + 1
        elif c == '"':
            i += 1
            buf = ['"']
            while True:
                if i >= len(s):
                    raise _Deny("unbalanced quotes")
                if s[i] == "\\":
                    buf.append(s[i:i + 2])
                    i += 2
                elif s[i] == '"':
                    buf.append('"')
                    i += 1
                    break
                elif s.startswith("$((", i):
                    i = _arith_end(s, i + 1)
                    buf.append("0")
                elif s.startswith("$(", i):
                    i = _scan(s, i + 2, ")", segs, meta, pipeamp, depth + 1)
                    buf.append("X")
                elif s[i] == "`":
                    i = _scan(s, i + 1, "`", segs, meta, pipeamp, depth + 1)
                    buf.append("X")
                else:
                    buf.append(s[i])
                    i += 1
            cur.append("".join(buf))
        elif s.startswith("$((", i):
            i = _arith_end(s, i + 1)
            cur.append("0")
        elif s.startswith("$(", i):
            i = _scan(s, i + 2, ")", segs, meta, pipeamp, depth + 1)
            cur.append("X")
        elif c == "`":
            i = _scan(s, i + 1, "`", segs, meta, pipeamp, depth + 1)
            cur.append("X")
        elif s.startswith("${", i):
            j = s.find("}", i)
            if j < 0:
                raise _Deny("unbalanced ${")
            if "$(" in s[i:j] or "`" in s[i:j]:             # v2 пропускал ${x:-$(prog)} не глядя
                raise _Deny(NO_SUBST_MSG)
            cur.append(s[i:j + 1])
            i = j + 1
        elif dbl and s.startswith("]]", i):
            dbl = False
            cur.append("]]")
            i += 2
        elif dbl and (s.startswith("&&", i) or s.startswith("||", i)):
            cur.append(s[i:i + 2])
            i += 2
        elif dbl and c in "<>()|":
            cur.append(c)
            i += 1
        elif s.startswith("[[", i) and _cmd_pos(cur) and s[i + 2:i + 3] in (" ", "\t", "\n"):
            dbl = True                                      # v3: [[ "$a" > "$b" ]] — сравнение, не запись
            cur.append("[[")
            i += 2
        elif s.startswith("((", i) and _cmd_pos(cur):
            i = _arith_end(s, i)                            # v3: (( n > 3 )) — арифметика, не запись
            cur.append(":")
        elif s.startswith("<<", i):
            raise _Deny(HEREDOC_PY_MSG if PYTHON else
                        "here-documents (<<) are not supported; pass text with echo or printf through a pipe")
        elif s.startswith("<(", i):
            i = _scan(s, i + 2, ")", segs, meta, pipeamp, depth + 1)   # v3: подстановка процесса — команда проверяется
            cur.append("X")
            st["procsub"] = True
        elif s.startswith(">(", i):
            raise _Deny("output process substitution >(...) is not supported; use a pipe")
        elif c in "<>" or s.startswith("&>", i):
            # номер дескриптора перед > (2>/dev/null) уже лежит в cur — убрать
            if cur and cur[-1].isdigit() and (len(cur) < 2 or cur[-2].isspace()):
                cur.pop()
            m = re.match(r"(&>>?|>>?&?|<&?)\s*([^\s|;&<>()]*)", s[i:])
            op, target = m.group(1), m.group(2)
            if op.startswith("<"):
                st["redir_in"] = True                       # чтение из файла: можно
            elif target == "/dev/null" or (op.endswith("&") and target.isdigit()) or op == ">&" and target.isdigit():
                pass
            elif op == ">" and target.startswith("&") and target[1:].isdigit():
                pass
            else:
                raise _Deny(f"'{op}{target}': {READONLY_MSG}")
            cur.append(" ")
            i += m.end()
        elif c == "#" and (i == 0 or s[i - 1] in " \t\n;|&("):
            j = s.find("\n", i)                             # комментарий оболочки — до конца строки
            i = len(s) if j < 0 else j
        elif s.startswith("&&", i) or s.startswith("||", i):
            cut()
            i += 2
        elif s.startswith("|&", i):                         # v3: |& = 2>&1 | (bash 3.2 его не знает — заменим)
            if pipeamp is not None:
                pipeamp.append(i)
            cut(True)
            i += 2
        elif c == "&":
            raise _Deny("background jobs ('&') are not allowed")
        elif c == "|":
            cut(True)
            i += 1
        elif c == "(":
            cut(st["piped"])                                # cmd | ( ... ): первая команда группы читает пайп
            i += 1
        elif c in ";\n)":
            cut()
            i += 1
        else:
            cur.append(c)
            i += 1
    if close:
        raise _Deny(f"unbalanced '{'$(' if close == ')' else close}'")
    if dbl:
        raise _Deny("unbalanced '[['")
    cut()
    return i


def _strip_kw(w):
    while w and (w[0] in KEYWORDS or re.match(r"^[A-Za-z_]\w*=", w[0])):
        w = w[1:]
    return w


def _awk_bad(prog):
    """Есть ли в программе awk system(), getline или вывод print/printf в файл/команду (> >> |).
    Сравнение вне print ($3 > "a", if (x > y)) — можно; строки и /регэкспы/ пропускаются."""
    i, n = 0, len(prog)
    depth, in_print, pdepth, prev = 0, False, 0, ""
    while i < n:
        c = prog[i]
        if c == '"' or (c == "/" and (prev == "" or prev in "(,~!{;&|?:\n")):
            j = i + 1
            while j < n and prog[j] != c:
                j += 2 if prog[j] == "\\" else 1
            i, prev = j + 1, c
            continue
        if c == "#":
            j = prog.find("\n", i)
            i = n if j < 0 else j
            continue
        if c.isalpha() or c == "_":
            word = re.match(r"[A-Za-z_]\w*", prog[i:]).group(0)
            if word in ("system", "getline"):
                return word
            if word in ("print", "printf"):
                in_print, pdepth = True, depth
            i += len(word)
            prev = "a"
            continue
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        elif c in "{};\n":
            in_print = False
        elif c in ">|" and in_print and depth == pdepth:
            if prog[i:i + 2] == "||":
                i += 2
                prev = "|"
                continue
            return "redirect"
        if not c.isspace():
            prev = c
        i += 1
    return None


def _awk_check(w):
    i = 1
    while i < len(w):
        x = w[i]
        if x == "--":
            i += 1
            break
        if x.startswith("-f"):
            return "awk -f (program from a file) is not allowed; give the program inline"
        if x in ("-F", "-v"):
            i += 2
        elif x.startswith("-") and len(x) > 1:
            i += 1
        else:
            break
    if i < len(w) and _awk_bad(w[i]):
        return "awk may only read and print (no system(), getline, or print/printf output to files or commands with > or |)"
    return None


XARGS_VAL = set("EIJLnPRsS")        # ключи xargs BSD со значением


def _xargs_cmd(w):
    """xargs [ключи] [программа арг...] -> программа с аргументами (без программы xargs запускает echo)."""
    i = 1
    while i < len(w) and w[i].startswith("-") and len(w[i]) > 1:
        x = w[i]
        i += 1
        if x == "--":
            break
        for k, ch in enumerate(x[1:]):
            if ch in XARGS_VAL:
                if k == len(x) - 2:
                    i += 1                                  # значение — следующее слово (-I {} / -n 1)
                break
    return w[i:] or ["echo"]


def _check_words(w, m, via_xargs=False):
    p = w[0]
    if p in ("report", "finish"):
        return (f"'{p}' is a separate tool, not a shell command: call the {p} tool directly instead of bash"
                + (", e.g. " + REPORT_EXAMPLE if p == "report" else "") + ".")
    if p in WRITE_PROGS:
        return f"'{p}' writes files: {READONLY_MSG}"
    if p not in ALLOWED:
        return f"'{p}' is not allowed. Allowed programs: {', '.join(sorted(ALLOWED))}"
    if via_xargs and (p in BUILTINS or p == "xargs"):
        return (f"xargs can only run a program from the list, not '{p}'; "
                "use a loop instead: ... | while read f; do ...; done")
    if p == "sed" and any(x.startswith("-i") or x.startswith("-I") or x.startswith("--in-place") for x in w[1:]):
        return f"sed -i is not allowed: {READONLY_MSG}"
    if p == "awk":
        return _awk_check(w)
    if p == "find" and FIND_BAD & set(w):
        return "find actions like -exec/-delete are not allowed; pipe the file list into grep, head, xargs or a for loop"
    if p == "sort" and any(x == "-o" or x.startswith("--output") or x.startswith("--compress") for x in w):
        return f"sort -o is not allowed: {READONLY_MSG}"
    if p == "diff" and (m.get("procsub") or m.get("piped") and "-" in w[1:]
                        or any(x in ("-", "/dev/stdin") or x.startswith("/dev/fd/") for x in w[1:])):
        return ("diff can only compare two files here (for piped input or <(...) it needs a temporary file, and "
                "nothing can be written). To compare command outputs use comm: comm -3 <(cmd1 | sort) <(cmd2 | sort)")
    if p == "xargs":
        return _check_words(_xargs_cmd(w), {}, via_xargs=True)
    return None


def check_command(cmd, parsed=None, pipeamp=None):
    """Проверка командной строки: каждая простая команда (в т.ч. внутри $(...), <(...), циклов, if/while и после
    xargs) — из белого списка. Безопасность держит sandbox-exec (запись, сеть, чтение вне вида); белый список не
    даёт запустить интерпретатор/eval. parsed (v3) <- [(слова, meta)] для подсказок. -> текст ошибки или None."""
    if "\x00" in cmd:
        return "the command contains a NUL byte (\\x00); shell commands cannot contain it"
    try:
        cmd.encode("utf-8")
    except UnicodeEncodeError:
        return "the command contains characters that are not valid UTF-8 (a lone surrogate); retype it"
    if len(cmd) > MAX_CMD:
        return f"the command is {len(cmd)} characters long; the limit is {MAX_CMD}. Split it into shorter commands"
    segs, meta = [], []
    try:
        _scan(cmd, 0, None, segs, meta, pipeamp)
    except _Deny as e:
        return str(e)
    for s, m in zip(segs, meta):
        try:
            w = _strip_kw(shlex.split(s))
        except ValueError as e:
            return f"cannot parse: {e}"
        if not w:
            continue
        if parsed is not None:
            parsed.append((w, m))
        if w[0] == "for":
            if len(w) < 3 or not re.fullmatch(r"[A-Za-z_]\w*", w[1]) or w[2] != "in":
                return "loops must look like: for f in logs/*; do head -n 3 \"$f\"; done"
            continue
        err = _check_words(w, m)
        if err:
            return err
    return None


# ---------------------------------------------------------------- исполнение

def _killpg(pid):
    try:
        os.killpg(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def _exited(pid, timeout):
    """Ждать завершения лидера, не собирая его (WNOWAIT): pid остаётся занятым до p.wait(). -> завершился ли."""
    end, d = time.monotonic() + timeout, 0.001
    while True:
        try:
            if os.waitid(os.P_PID, pid, os.WEXITED | os.WNOWAIT | os.WNOHANG) is not None:
                return True
        except ChildProcessError:
            return True
        if time.monotonic() >= end:
            return False
        time.sleep(d)
        d = min(d * 2, 0.02)


def _collect(p, deadline):
    """stdout и stderr потоком до EOF/срока; stdout не больше MAX_CAPTURE байт (дальше — capped), stderr
    дочитывается, но хранится не больше MAX_STDERR. -> (stdout, stderr, capped, timed_out)"""
    sel = selectors.DefaultSelector()
    bufs = {p.stdout: bytearray(), p.stderr: bytearray()}
    caps = {p.stdout: MAX_CAPTURE, p.stderr: MAX_STDERR}
    for f in bufs:
        sel.register(f, selectors.EVENT_READ)
    capped = timed = False
    while sel.get_map() and not capped:
        left = deadline - time.monotonic()
        if left <= 0:
            timed = True
            break
        for key, _ in sel.select(timeout=left):
            f = key.fileobj
            chunk = os.read(f.fileno(), 65536)
            if not chunk:
                sel.unregister(f)
                continue
            b = bufs[f]
            room = caps[f] - len(b)
            b += chunk[:max(0, room)]
            if f is p.stdout and len(chunk) > room:
                capped = True
    sel.close()
    return bytes(bufs[p.stdout]), bytes(bufs[p.stderr]), capped, timed


def run_bash(cmd, root, prof, info=None):
    """-> (ok, text). v3: своя группа процессов (по таймауту/потолку убивается вся, сирот нет), stdin=/dev/null,
    вывод читается потоком с потолком MAX_CAPTURE. info <- pid, rc, capped, timed_out, parsed, notes."""
    info = {} if info is None else info
    parsed, pipeamp = [], []
    body = None
    if PYTHON:
        hd = split_heredoc(cmd)
        if hd:
            cmd, body = hd
            info["heredoc"] = True
    err = check_command(cmd, parsed, pipeamp)
    info.update(parsed=parsed, notes=[], capped=False, timed_out=False, pid=None, rc=None)
    if err:
        return False, f"Error: {err}"
    run = cmd
    for j in reversed(pipeamp):
        run = run[:j] + " 2>&1 |" + run[j + 2:]
    deadline = time.monotonic() + CMD_TIMEOUT
    env = {"PATH": "/usr/bin:/bin", "LANG": "en_US.UTF-8", "HOME": root}
    if PYTHON or RUNS_TOOL:
        env.update(PATH=f"{BIN}:/usr/bin:/bin", PYTHONDONTWRITEBYTECODE="1", RUNS_OUT_CHARS=str(OUT_CHARS), RUNS_FORMAT=RUNS_FORMAT)
    p = subprocess.Popen(["sandbox-exec", "-f", prof, "/bin/bash", "--noprofile", "--norc", "-c", run],
                         cwd=root, stdin=subprocess.DEVNULL if body is None else subprocess.PIPE,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True, env=env)
    if body is not None:
        threading.Thread(target=_feed, args=(p.stdin, body.encode("utf-8")), daemon=True).start()
    info["pid"] = p.pid
    out = er = b""
    capped = timed = False
    try:
        out, er, capped, timed = _collect(p, deadline)
        if not (capped or timed) and not _exited(p.pid, max(0.5, deadline - time.monotonic())):
            timed = True
    finally:
        # v3c: группа убивается до reap. Пока лидер не собран (жив или зомби), его pid = pgid занят и не может
        # достаться чужой группе; после p.wait() killpg мог бы попасть в чужую. Остатки группы (процесс закрыл
        # вывод и работает дальше) гибнут здесь же.
        _killpg(p.pid)
        rc = p.wait()
        p.stdout.close()
        p.stderr.close()
    info.update(rc=rc, capped=capped, timed_out=timed)
    if timed:
        return False, f"Error: command timed out after {CMD_TIMEOUT}s; narrow it (search fewer files, use head)."
    out = out.decode("utf-8", "replace")
    er = er.decode("utf-8", "replace").replace(root + "/", "").replace(root, ".")
    er = XARGS_PIPE_RE.sub("", er)                      # ... | xargs ... | head: xargs жалуется на закрытый пайп
    text = out + (("\n[stderr]\n" + er) if er.strip() else "")
    if rc and not text.strip():
        text = f"(no output, exit code {rc})"
    elif not text:
        text = "(no output)"
    note = _stdin_note(parsed, cmd, empty=not out.strip())
    if note:
        info["notes"].append(note)
    if er.strip():
        info["notes"] += _layout_notes(cmd, er, root) + _bsd_notes(er)
    return True, text


def _feed(f, data):
    """Тело heredoc -> stdin команды (в потоке: команда может не читать stdin, пайп не должен зависнуть)."""
    try:
        f.write(data)
    except OSError:
        pass
    finally:
        try:
            f.close()
        except OSError:
            pass


def bash_output(cmd, root, prof):
    """Команда -> (ok, что видит модель, полный вывод, info, обрезано ли). Заметки идут после обрезки."""
    info = {}
    ok, full = run_bash(cmd, root, prof, info)
    shown, tr = clip(full, cmd, root, info.get("capped"), info.get("parsed"))
    if info.get("notes"):
        shown += "\n" + "\n".join(f"[note: {n}]" for n in info["notes"])
    return ok, shown, full, info, tr


# ---------------------------------------------------------------- подсказки к выводу

# программы, читающие stdin, если файла нет; ключи со значением в следующем слове
STDIN_PROGS = {
    "cat": set(), "head": {"-n", "-c"}, "tail": {"-n", "-c"}, "wc": set(), "sort": {"-k", "-t", "-T", "-S"},
    "uniq": {"-f", "-s"}, "cut": {"-d", "-f", "-c", "-b"}, "nl": {"-b", "-d", "-f", "-h", "-i", "-l", "-n", "-s", "-v", "-w"},
    "rev": set(), "column": {"-c", "-s"}, "paste": {"-d"}, "od": {"-A", "-j", "-N", "-t"}, "xxd": {"-c", "-g", "-l", "-s", "-o"},
    "grep": {"-e", "-f", "-A", "-B", "-C", "-m", "-d", "-D", "--include", "--exclude", "--exclude-dir", "--context"},
    "sed": {"-e", "-f"}, "awk": {"-F", "-v", "-f"}, "tr": set(),
    "jq": {"--arg", "--argjson", "--rawfile", "--slurpfile", "-f", "--indent"},
}
XARGS_PIPE_RE = re.compile(r"^xargs: .*terminated with signal 13; aborting\n?", re.M)
NOFILE_EXAMPLE = {"grep": "grep -n PATTERN FILE (or grep -rn PATTERN DIR for a directory)", "sed": "sed -n '1,40p' FILE", "awk": "awk -F'|' '{print $1}' FILE"}


def _operands(w):
    """Файловые аргументы программы-фильтра (None — программа не читает stdin)."""
    p = w[0]
    vals = STDIN_PROGS.get(p)
    if vals is None:
        return None
    i, explicit = 1, False
    while i < len(w) and w[i].startswith("-") and w[i] != "-":
        x = w[i]
        i += 1
        if x == "--":
            break
        if p in ("grep", "sed") and re.fullmatch(r"-[a-zA-Z]*[ef]", x):
            explicit = True                                 # -e PATTERN / -f FILE: шаблон не позиционный
            i += 1
        elif p in ("grep", "sed") and re.match(r"-[ef].", x) or p == "awk" and x.startswith("-f"):
            explicit = True
            i += x == "-f"
        elif x in vals:
            i += 1
    rest = w[i:]
    if p in ("grep", "sed", "awk") and not explicit:
        rest = rest[1:]                                     # шаблон / скрипт / программа
    if p == "awk":
        rest = [r for r in rest if not re.match(r"^[A-Za-z_]\w*=", r)]
    if p == "tr":
        rest = []                                           # tr читает только stdin
    return rest


def _stdin_note(parsed, cmd, empty=True):
    """Фильтр не получил ни файла, ни пайпа (stdin тут пустой) -> заметка для модели. Нет файлового аргумента
    вовсе — заметка всегда (wc -l печатает 0 и без входа); аргумент-переменная — только при пустом выводе."""
    any_in = bool(re.search(r"<(?![(<])", cmd))
    for w, m in parsed:
        if m.get("piped") or m.get("redir_in"):
            continue
        p = w[0]
        if p == "read":
            if not any_in:
                return ("`read` got no input: nothing is piped into it and there is no other input here. "
                        "Pipe a list into the loop, e.g. ls logs | while read f; do ...; done")
            continue
        ops = _operands(w)
        if ops is None:
            continue
        if not ops or ops == ["-"]:
            return (f"`{p}` was given no file and nothing was piped into it, so it read nothing (input comes only "
                    f"from files and pipes here). Name the file, e.g. {NOFILE_EXAMPLE.get(p, p + ' FILE')}")
        var = [o for o in ops if re.fullmatch(r"\$\{?[A-Za-z_]\w*\}?|X", o)]
        if empty and var and len(var) == len(ops):
            v = var[0]
            name = re.sub(r"[${}]", "", v)
            if v != "X" and re.search(rf"\bfor\s+{name}\s+in\b", cmd):
                continue                                    # переменная цикла: пустой вывод = нет совпадений
            shown = "the $(...) result" if v == "X" else v
            return (f"if {shown} was empty, `{p}` got no file name and read nothing (there is no input here except "
                    f"files and pipes); check it, e.g. echo \"[{'$(...)' if v == 'X' else v}]\"")
    return None


NOFILE_RE = re.compile(r"([^\s:'\"]+): No such file or directory")
STEP_RE = re.compile(r"(\d+)\.(py|out)(\..+)?")


def _layout_notes(cmd, er, root):
    """«No such file» на logs/run_N.jsonl, которого нет в виде -> заметка, где список run."""
    notes = []
    for path in dict.fromkeys(NOFILE_RE.findall(er)):
        if re.search(r"(^|/)run_\d+\.jsonl$", path) and not os.path.isfile(os.path.join(root, path)):
            notes.append("logs/results.jsonl lists the runs in this directory.")
    return list(dict.fromkeys(notes))[:3]


BSD_NOTES = [
    (re.compile(r"grep: (?:invalid|unrecognized) option -- '?P"), "BSD grep has no -P; use grep -E (write [0-9] for \\d)."),
    (re.compile(r"find: -printf: unknown primary"), "BSD find has no -printf; print the paths and shorten them with "
                                                     "basename, dirname or sed."),
    (re.compile(r"head: illegal line count -- 0"), "BSD head needs a count of at least 1."),
    (re.compile(r"(?:illegal|invalid|unrecognized) option|unknown primary"),
     "these are macOS/BSD utilities; GNU-only options do not exist here."),
]


def _bsd_notes(er):
    for rx, note in BSD_NOTES:
        if rx.search(er):
            return [note]
    return []


COUNT_MAX = 10 * 2**20      # v3c: строки считаем не дальше 10 МБ


def _count_lines(path, limit=COUNT_MAX):
    """Строк в файле (как sed -n/grep -n: по \\n, хвост без \\n — строка). Читается кусками; файл больше limit
    байт -> None (не считаем: память и время не растут с размером)."""
    n, last, size = 0, b"", 0
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1 << 20)
            if not chunk:
                break
            size += len(chunk)
            if size > limit:
                return None
            n += chunk.count(b"\n")
            last = chunk[-1:]
    return n + (1 if size and last != b"\n" else 0)


def _file_map(cmd, root, parsed):
    """Команда — чтение одного файла (cat F, sed -n 'a,bp' F, head/tail -n N F; перед ней можно cd) ->
    (путь от корня вида, номер строки файла перед выводом, последняя строка диапазона, строк в файле)."""
    if not parsed or root is None or "|" in cmd or "$" in cmd.replace("$p'", "") or "`" in cmd:
        return None
    if any(m.get("piped") or m.get("procsub") for _, m in parsed):
        return None
    *cds, (w, _) = parsed
    base = root
    for cw, _ in cds:
        if cw[0] != "cd" or len(cw) != 2:
            return None
        base = os.path.normpath(os.path.join(base, cw[1].replace("~", root, 1)))
    p, f, off, end = w[0], None, 0, None
    if p == "cat" and len(w) == 2:
        f = w[1]
    elif p == "sed" and len(w) == 4 and w[1] == "-n":
        m = re.fullmatch(r"(\d+)(?:,(\d+|\$))?p", w[2])
        if m:
            f, off = w[3], int(m.group(1)) - 1
            end = int(m.group(2) or m.group(1)) if m.group(2) != "$" else None
    elif p in ("head", "tail"):
        a, n = w[1:], "10"
        if len(a) >= 2 and a[0] == "-n":
            n, a = a[1], a[2:]
        elif a and re.fullmatch(r"-n?\+?\d+", a[0]):
            n, a = a[0].lstrip("-n"), a[1:]
        if len(a) == 1 and re.fullmatch(r"\+?\d+", n):
            f = a[0]
            if p == "tail":
                off = int(n[1:]) - 1 if n.startswith("+") else None
                tail_n = int(n)
    if not f or f.startswith("-") or re.search(r"[*?\[{~]", f):
        return None
    full = os.path.normpath(os.path.join(base, f))
    if not full.startswith(root + "/") or not os.path.isfile(full):
        return None
    nl = _count_lines(full)
    if nl is None:
        return None                                     # v3c: файл больше COUNT_MAX — общая подсказка
    if off is None:
        off = max(0, nl - tail_n)
    end = min(end or nl, nl)
    return os.path.relpath(full, root), off, end, nl


# ---------------------------------------------------------------- учёт чтения трасс (только лог; модель не видит)

READ_PROGS = {"cat", "head", "tail", "sed", "nl", "awk", "grep", "cut", "sort", "uniq", "column", "paste", "rev",
              "od", "xxd", "jq", "diff", "comm"}       # показывают содержимое файла; ls, find, wc, test — нет
VAR_RE = re.compile(r"\$\{?([A-Za-z_]\w*)\}?")
ASSIGN_RE = re.compile(r"(?:^|[;&|\n(]|\bdo|\bthen)\s*([A-Za-z_]\w*)=(\"[^\"`]*\"|'[^']*'|[^\s;&|`()]*)(?=[\s;&|)]|$)")
STEP_FILE_RE = re.compile(r"^run_\d+\.jsonl$")      # view: файл run
MAX_COMBOS = 2000


def _braces(w):
    """Раскрытие {a,b} как в bash (вложенные — рекурсией); {} без запятой не трогается."""
    m = re.search(r"\{([^{}]*,[^{}]*)\}", w)
    if not m:
        return [w]
    out = []
    for alt in m.group(1).split(","):
        out += _braces(w[:m.start()] + alt + w[m.end():])
    return out


def _subst(word, env, wild=False):
    """Слово -> список слов с подставленными переменными цикла/присваивания; None — есть неизвестная переменная.
    wild: неизвестная переменная и $(...) (у разбора — X) -> glob '*' (какие файлы — неизвестно, run — по пути)."""
    for _ in range(3):                                  # присваивание со ссылкой на другую переменную: run="runs/$f"
        known = [n for n in dict.fromkeys(VAR_RE.findall(word)) if n in env and len(env[n]) == 1
                 and VAR_RE.search(env[n][0])]
        if not known:
            break
        for n in known:
            word = re.sub(r"\$\{?" + n + r"\b\}?", lambda _m, v=env[n][0]: v, word)
    def _split(m):                                      # разбор снимает кавычки: "$d"task.md -> $dtask.md
        n = m.group(1)
        if n in env or m.group(0).startswith("${"):
            return m.group(0)
        pre = max((v for v in env if n.startswith(v)), key=len, default=None)
        return "${" + pre + "}" + n[len(pre):] if pre else m.group(0)
    word = VAR_RE.sub(_split, word)
    names = list(dict.fromkeys(VAR_RE.findall(word)))
    if any(n not in env for n in names):
        if not wild:
            return None
        word = VAR_RE.sub(lambda m: m.group(0) if m.group(1) in env else "*", word)
        names = [n for n in names if n in env]
    words = [word]
    for n in names:
        rx = re.compile(r"\$\{?" + n + r"\b\}?")
        words = [rx.sub(lambda _m, v=v: v, x) for x in words for v in env[n]][:MAX_COMBOS]
    return words


def _expand(word, bases, root):
    """Слово-операнд -> существующие пути внутри вида (относительно корня): brace, glob, относительно cd."""
    out = []
    for b in bases:
        for w in _braces(word):
            full = os.path.normpath(os.path.join(b, w.replace("~", root, 1) if w.startswith("~") else w))
            hits = sorted(glob.glob(full)) if re.search(r"[*?\[]", w) else [full]
            for h in hits:
                h = os.path.normpath(h)
                if (h == root or h.startswith(root + "/")) and os.path.exists(h):
                    out.append(os.path.relpath(h, root) + ("/" if w.endswith("/") and h != root else ""))
    return list(dict.fromkeys(out))


def _run_of(rel):
    """view: путь от корня -> (номер run, имя файла) для logs/run_N.jsonl; 'logs' и '.' -> ('*', None)."""
    parts = [] if rel == "." else rel.rstrip("/").split("/")
    if not parts or parts == ["logs"]:
        return "*", None
    m = re.fullmatch(r"run_(\d+)\.jsonl", parts[-1]) if len(parts) == 2 and parts[0] == "logs" else None
    if m:
        return m.group(1), parts[-1]
    return None, None


def trace_reads(cmd, root, parsed):
    """Какие файлы трасс команда реально открыла программой, печатающей содержимое (cat/head/tail/sed/grep/awk/...),
    а не упомянула. Раскрываются cd, glob, {a,b}, переменные for и простые присваивания. Операнд, раскрывшийся в
    файлы одного run, — чтение этого run; операнд на несколько run (runs/*/..., grep -r по runs/ или .) — просмотр
    (scanned). grep -l/-L/-c/-q содержимого не показывает — не чтение. Операнд из stdin (xargs), $(...), read —
    unresolved. -> {"read": {run: [пути в run]}, "scanned": [run], "unresolved": [операнды]}."""
    read, scanned, unres = {}, set(), []
    if not parsed or root is None:
        return {"read": {}, "scanned": [], "unresolved": []}
    env = {}
    for m in ASSIGN_RE.finditer(cmd):
        if "$(" not in m.group(2):
            env[m.group(1)] = [m.group(2).strip("\"'")]
    try:
        all_runs = sorted(m.group(1) for f in os.listdir(os.path.join(root, "logs"))
                          for m in [re.fullmatch(r"run_(\d+)\.jsonl", f)] if m)
    except OSError:
        all_runs = []
    bases = [root]
    for w, meta in parsed:
        p = w[0]
        if p == "for" and len(w) >= 3 and w[2] == "in":
            vals, ok = [], True
            for x in w[3:]:
                s = _subst(x, env)
                if s is None or any("X" in y and not _expand(y, bases, root) for y in s):
                    ok = False
                    break
                for y in s:
                    exp = _expand(y, bases[:1], root) if bases and re.search(r"[*?\[{]", y) else []
                    # glob в списке for даёт пути от текущего каталога, как в bash
                    exp = [os.path.relpath(os.path.join(root, e), bases[0]) + ("/" if e.endswith("/") else "")
                           for e in exp]
                    vals += exp if exp else _braces(y)
            if ok:
                env[w[1]] = vals[:MAX_COMBOS]
            else:
                env.pop(w[1], None)
            continue
        if p == "read":
            for n in w[1:]:
                if not n.startswith("-"):
                    env.pop(n, None)
            continue
        if p == "cd":
            arg = w[1] if len(w) > 1 else root
            s = [y.replace("X", "*") for y in _subst(arg, env, wild=True)]
            nb = []
            for b in bases:
                for y in s:
                    for y2 in _braces(y):
                        full = os.path.normpath(os.path.join(b, y2.replace("~", root, 1) if y2.startswith("~") else y2))
                        nb += sorted(glob.glob(full)) if re.search(r"[*?\[]", y2) else [full]
            bases = list(dict.fromkeys(os.path.normpath(x) for x in nb if os.path.isdir(x)
                                       and (os.path.normpath(x) == root or x.startswith(root + "/"))))
            continue
        if p == "xargs":
            prog = fsr_xargs_prog(w)
            if prog in READ_PROGS:
                unres.append(" ".join(w)[:200])
            continue
        if p not in READ_PROGS:
            continue
        if p in ("diff", "comm"):
            ops = [x for x in w[1:] if not x.startswith("-")]
        else:
            ops = _operands(w)
            if ops is None:
                ops = [x for x in w[1:] if not x.startswith("-")]
        flags = [x for x in w[1:] if x.startswith("-") and not x.startswith("--")]
        if p == "grep":
            if any(re.search(r"[lLcq]", x[1:]) for x in flags if re.fullmatch(r"-[a-zA-Z]+", x)) or any(
                    x in ("--files-with-matches", "--files-without-match", "--count", "--quiet") for x in w[1:]):
                continue
            recursive = any(re.fullmatch(r"-[a-zA-Z]*[rR][a-zA-Z]*", x) for x in flags) or "--recursive" in w
        else:
            recursive = False
        for o in ops:
            if o == "-":
                continue
            s = _subst(o, env)
            wild = s is None
            if wild:
                s = _subst(o, env, wild=True)
            if not bases:
                unres.append(o[:200])
                continue
            hits = []
            for y in s:
                h = _expand(y, bases, root)
                if not h and "X" in y:
                    h = _expand(y.replace("X", "*"), bases, root)
                    wild = wild or bool(h)
                hits += h
            if not hits:
                continue                                # нет такого файла: ничего не открыто
            runs, files = set(), []
            for h in hits:
                rid, inner = _run_of(h)
                full = os.path.join(root, h)
                if os.path.isdir(full):
                    if not recursive:
                        continue                        # cat/sed по каталогу ничего не читают
                    if rid == "*":
                        runs |= set(all_runs)
                        files.append(("*", None))
                    elif rid:
                        runs.add(rid)
                        files.append((rid, inner or ""))
                elif rid and rid != "*":
                    runs.add(rid)
                    files.append((rid, inner))
            if len(runs) == 1:
                rid = next(iter(runs))
                for r_, inner in files:
                    inner = (inner or "").rstrip("/")
                    if wild:
                        inner = "?" + inner                 # файл угадан по glob вместо переменной
                    read.setdefault(rid, [])
                    if inner not in read[rid]:
                        read[rid].append(inner)
            elif runs:
                scanned |= runs
    return {"read": {r: sorted(v) for r, v in sorted(read.items())}, "scanned": sorted(scanned - set(read)),
            "unresolved": list(dict.fromkeys(unres))}


def fsr_xargs_prog(w):
    try:
        return _xargs_cmd(w)[0]
    except Exception:  # noqa: BLE001
        return None


def _is_trace_read(inner_files):
    """Run прочитан как трасса: открыт файл шага или каталог шагов/run (grep -r внутри run)."""
    return any(STEP_FILE_RE.match(f.lstrip("?")) for f in inner_files)


def _pipe_hint(cmd, tail):
    c = (cmd or "").strip().rstrip(";").strip()
    if not c or "\n" in c or "#" in c or len(c) > 200:
        return f"run the same command again with `| {tail}` added at the end (wrap it as {{ ...; }} if it has several parts)"
    if re.search(r";|&&|\|\|", c):
        c = "{ " + c + "; }"
    return f"`{c} | {tail}`"


def clip(text, cmd=None, root=None, capped=False, parsed=None):
    """Обрезка вывода до OUT_CHARS. v3: подсказка «как дочитать» с номерами строк самого файла (одиночное чтение
    файла) или командой `<cmd> | sed -n 'a,bp'`; для строки длиннее OUT_CHARS — cut -c."""
    if len(text) <= OUT_CHARS and not capped:
        return text, False
    shown = text[:OUT_CHARS]
    k = shown.count("\n")
    if capped:
        total = f"more than {MAX_CAPTURE} bytes (the command was stopped there)"
    else:
        total = f"{len(text)} characters, {text.count(chr(10)) + (not text.endswith(chr(10)))} lines"
    fm = _file_map(cmd, root, parsed) if cmd else None
    c1, c2 = OUT_CHARS + 1, 2 * OUT_CHARS
    if k == 0:
        what = f"the first line alone is longer than {OUT_CHARS} characters"
        how = (f"`sed -n '{fm[1] + 1}p' {fm[0]} | cut -c {c1}-{c2}`" if fm
               else _pipe_hint(cmd, f"head -n 1 | cut -c {c1}-{c2}"))
    elif fm:
        rel, off, end, nl = fm
        a = off + k + 1
        b = max(a, min(end, a + 149))
        what = f"shown: lines {off + 1}-{off + k} of {rel}, which has {nl} lines"
        how = f"`sed -n '{a},{b}p' {rel}`"
    else:
        what = f"shown: lines 1-{k} of the output"
        how = _pipe_hint(cmd, f"sed -n '{k + 1},{k + 150}p'")
    return (shown + f"\n\n[output truncated: showing the first {OUT_CHARS} of {total}; {what}. "
            f"To read on: {how}. Or narrow it with grep -n.]"), True



# ---------------------------------------------------------------- report

EV_RE = re.compile(r"^\s*(?:\./)?([^:\s]+):L?(\d+)(?:\.\d+)?(?:\s*-\s*L?(\d+)(?:\.\d+)?)?(?:[:\s].*)?$", re.S)
EV_LIST_RE = re.compile(r"^\s*(?:\./)?([^:\s]+):(\d+(?:\s*,\s*\d+)+)\s*$")     # v3b: path:455,463,471
EV_TEXT_RE = re.compile(r"^\s*(?:\./)?([^\s:]+)\s*:\s+\D.*$", re.S)               # v3b: 'path: цитата'
RUN_FILE_RE = re.compile(r"(?!)")                                                  # view: исключения для файла run нет
EV_FILE_RE = re.compile(r"^\s*(?:\./)?([^:\s]+)\s*$")
WHOLE_FILE_MAX = 80


def check_evidence(ev, root):
    """-> (ошибки, нормализованные ссылки). Короткий файл можно сослать путём целиком (-> path:1-N)."""
    if not isinstance(ev, list) or not ev:
        return ["evidence must be a non-empty list of 'path:line' or 'path:start-end' strings"], []
    errs, norm = [], []
    items = []
    for e in ev:
        e = str(e)
        ml = EV_LIST_RE.match(e)
        items += [f"{ml.group(1)}:{x.strip()}" for x in ml.group(2).split(",")] if ml else [e]
    for e in items:
        if "\x00" in e:
            errs.append(f"{e!r}: contains a NUL byte (\\x00); give a plain 'path:line' reference")
            continue
        m = EV_RE.match(e)
        mf = None if m else (EV_FILE_RE.match(e) or EV_TEXT_RE.match(e))
        if not m and not mf:
            errs.append(f"{e!r}: expected 'path:line' or 'path:start-end'")
            continue
        path = (m or mf).group(1)
        full = os.path.realpath(os.path.join(root, path))
        if not full.startswith(root + "/") or not os.path.isfile(full):
            errs.append(f"{e!r}: no such file '{path}'")
            continue
        n = _count_lines(full)                          # v3c: потоково (был построчный open: строка 1 ГБ — в память)
        if n is None:
            errs.append(f"{e!r}: '{path}' is too large to cite")
            continue
        if mf:
            if n > WHOLE_FILE_MAX and not RUN_FILE_RE.match(path):
                errs.append(f"{e!r}: '{path}' has {n} lines; cite the lines you mean, e.g. '{path}:12-30'")
                continue
            a, b = 1, max(1, n)
        else:
            a, b = int(m.group(2)), int(m.group(3) or m.group(2))
            if 1 <= a <= n < b:
                b = n                                           # v2.2: конец диапазона за концом файла -> до конца
            elif a > n and n <= WHOLE_FILE_MAX:
                a, b = 1, max(1, n)                             # v3b: начало за концом короткого файла -> целиком
        if not (1 <= a <= b <= max(1, n)):
            errs.append(f"{e!r}: '{path}' has {n} lines")
            continue
        norm.append(f"{path}:{a}" if a == b else f"{path}:{a}-{b}")
    return errs, norm


EV_HEAD_RE = re.compile(r"^\s*(?:\./)?([^\s:]+)(?::|\s*$)")     # A7: первое слово перед ':' (или единственное)
PATHLIKE_RE = re.compile(r"/|\.[A-Za-z]{1,6}$")                  # похоже на путь: есть '/' или расширение


def check_evidence_free(ev, root):
    """A7, EVIDENCE_MODE=free: непустой список строк в любой форме. Если элемент начинается с пути (path, path:...,
    'path: цитата'), путь должен существовать в виде (файл или каталог); номера строк и цитаты не проверяются.
    -> (ошибки, элементы как есть)."""
    if not isinstance(ev, list) or not [e for e in ev if str(e).strip()]:
        return ["evidence must be a non-empty list of strings"], []
    errs, norm = [], []
    for e in ev:
        e = str(e)
        if not e.strip():
            continue
        if "\x00" in e:
            errs.append(f"{e[:200]!r}: contains a NUL byte (\\x00)")
            continue
        m = EV_HEAD_RE.match(e)
        path = m.group(1) if m else None
        if path and PATHLIKE_RE.search(path.rstrip("/")):
            full = os.path.realpath(os.path.join(root, path))
            if not (full == root or full.startswith(root + "/")) or not os.path.exists(full):
                errs.append(f"{e[:200]!r}: no such file or directory '{path}'")
                continue
        norm.append(e)
    return errs, norm


# ---------------------------------------------------------------- экспорт

# v3c: ESC-последовательности (CSI, OSC до BEL/ST, прочие ESC x) и управляющие C0/C1, кроме \n и \t
CTRL_RE = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)?|\x1b\[[0-?]*[ -/]*[@-~]|\x1b[ -~]?|[\x00-\x08\x0b-\x1f\x7f-\x9f]")


def strip_controls(x):
    """Текст модели -> без управляющих символов (для экспорта и печати в терминал). Списки/словари — рекурсивно."""
    if isinstance(x, str):
        return CTRL_RE.sub("", x)
    if isinstance(x, list):
        return [strip_controls(v) for v in x]
    if isinstance(x, dict):
        return {k: strip_controls(v) for k, v in x.items()}
    return x


# ---------------------------------------------------------------- модель

def chat(messages, temp, seed, tools=None, tool_choice=None):
    body = {"model": MODEL, "messages": messages, "temperature": temp, "seed": seed, "max_tokens": MAX_GEN}
    url = URL
    if THINKING:
        url = THINK_URL
        body["enable_thinking"] = True
        if THINK_BUDGET:
            body["thinking_budget"] = THINK_BUDGET
    if tools:
        body["tools"] = tools
    if tool_choice:
        body["tool_choice"] = tool_choice
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "Authorization": "Bearer x"})
    try:
        with urllib.request.urlopen(req, timeout=1800) as r:
            return json.load(r), None
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}: {e.read().decode(errors='replace')[:500]}"
    except Exception as e:  # noqa: BLE001
        return None, f"{type(e).__name__}: {e}"


def est_tokens(text):
    return int(len(text) / 3.0) + 8


# ---------------------------------------------------------------- цикл

API_RETRIES = 2          # v3c: повторы при битом ответе API ({}, пустые choices, нет message)
API_RETRY_SEC = 5


def _int(x):
    return x if isinstance(x, int) and not isinstance(x, bool) else 0


def parse_response(resp):
    """v3c: ответ API -> {content, calls, bad, finish_reason, usage} или (None, причина). calls приведены к виду
    {"id", "function": {"name", "arguments": str}}; вызовы без function.name отбрасываются и считаются в bad."""
    if not isinstance(resp, dict):
        return None, "the response is not a JSON object"
    chs = resp.get("choices")
    if not isinstance(chs, list) or not chs or not isinstance(chs[0], dict):
        return None, "no choices in the response"
    ch = chs[0]
    msg = ch.get("message")
    if not isinstance(msg, dict):
        return None, "no message in choices[0]"
    raw = msg.get("tool_calls") or []
    bad = 0
    if not isinstance(raw, list):
        raw, bad = [], 1
    calls = []
    for c in raw:
        f = c.get("function") if isinstance(c, dict) else None
        name = f.get("name") if isinstance(f, dict) else None
        if not isinstance(name, str) or not name:
            bad += 1
            continue
        a = f.get("arguments")
        a = "" if a is None else a if isinstance(a, str) else json.dumps(a, ensure_ascii=False)
        cid = c.get("id")
        calls.append({"id": cid if isinstance(cid, str) and cid else None, "function": {"name": name, "arguments": a}})
    content = msg.get("content")
    if content is not None and not isinstance(content, str):
        content = json.dumps(content, ensure_ascii=False)
    u = resp.get("usage")
    det = u.get("prompt_tokens_details") if isinstance(u, dict) else None
    u = {k: _int(v) for k, v in u.items() if not isinstance(v, dict)} if isinstance(u, dict) else {}
    if isinstance(det, dict) and "cached_tokens" in det:       # v3b: префикс-кэш воркера (шлюз: prompt_tokens_details)
        u["cached_tokens"] = _int(det["cached_tokens"])
    fr = ch.get("finish_reason")
    rs = msg.get("reasoning") or msg.get("reasoning_content")
    return {"reasoning": rs if isinstance(rs, str) else None,
            "content": content, "calls": calls, "bad": bad, "finish_reason": fr if isinstance(fr, str) else None,
            "usage": u}, None


def session(mode, k, seed, temp, tag, resume=None, max_turns=None, runs=None):
    tids, sel = select(mode, k, seed, runs)
    name = f"r{'-'.join(map(str, tids))}_{POLICY}_s{seed}"
    # v3c: вид и профиль уникальны на сессию (tag в имени; занят живой сессией — ещё и _p<pid>)
    vname, lock = claim_view(f"{name}_{tag}")
    try:
        root = build_view(vname, tids)
        prof = sandbox_profile(root)
        os.makedirs(f"{HERE}/logs", exist_ok=True)
        suffix = vname[len(f"{name}_{tag}"):]
        logp = f"{HERE}/logs/{name}_{tag}{suffix}.jsonl"
        log = open(logp, "w", encoding="utf-8", errors="backslashreplace")   # v3c: одиночный суррогат не роняет запись
    except BaseException:
        release_view(lock)
        raise

    def w(rec):
        log.write(json.dumps(rec, ensure_ascii=False) + "\n")
        log.flush()

    st = {"turns": 0, "tool_calls": 0, "bash": 0, "reports_ok": 0, "reports_rejected": 0, "no_call": 0,
          "bad_call": 0, "repeats": 0, "denied": 0, "truncated": 0, "gen_tokens": 0, "max_prompt": 0,
          "model_sec": 0.0, "length_stops": 0, "clears": 0, "cleared_results": 0, "reminders": 0,
          "final_turns": 0, "first_report_call": None, "api_retries": 0, "harness_errors": 0,
          "traces_read": [], "n_traces_read": 0, "traces_read_exact": [], "runs_opened": [], "traces_scanned_only": [], "step_files_read": 0,
          "read_unresolved_calls": 0, "notes": 0, "compactions": 0,
          "bash_calls": 0, "bash_over_limit": 0, "final_rejected": 0, "final_fix_used": 0, "finish_deferred": 0,
          "repeat_run_max": 0, "loop_final": 0}
    reports = []
    end = None
    try:
        w({"type": "meta", "version": 3, "mechanics": "v3b-view", "policy": POLICY, "layout": LAYOUT,
           "tools": [x["function"]["name"] for x in TOOLS], "notes_tool": NOTES, "compact": COMPACT,
           "compact_req": COMPACT_REQ if COMPACT else None, "read_counter": 1, "variant": VARIANT, "mode": mode, "k": k, "seed": seed, "temperature": temp,
           "runs": tids, "selection": sel, "view": vname, "system": SYSTEM, "first_user": FIRST_USER, "limits": {
               "ctx": CTX, "max_gen": MAX_GEN, "warn_at": WARN_AT, "hard_at": HARD_AT, "clear_at": CLEAR_AT,
               "keep_results": KEEP_RESULTS, "step_budget": STEP_BUDGET, "remind_every": REMIND_EVERY,
               "final_turns": FINAL_TURNS, "out_chars": OUT_CHARS, "cmd_timeout": CMD_TIMEOUT,
               "max_capture": MAX_CAPTURE, "log_head": LOG_HEAD, "max_cmd": MAX_CMD, "max_depth": MAX_DEPTH,
               "api_retries": API_RETRIES, "clear_to": CLEAR_TO, "clear_at_least": CLEAR_AT_LEAST, "stub": STUB,
               "evidence_mode": EVIDENCE_MODE, "trace_mode": TRACE_MODE,
               "bash_limit": BASH_LIMIT, "final_fix_turns": FINAL_FIX_TURNS, "python": PYTHON,
               "runs_tool": RUNS_TOOL, "runs_format": RUNS_FORMAT, "runs_mode": RUNS_MODE, "say_first": SAY_FIRST, "checklist": CHECKLIST, "taxonomy": TAXONOMY, "diary": DIARY, "hypotheses": HYPOTHESES, "thinking": THINKING, "think_budget": THINK_BUDGET, "repeat_stop": REPEAT_STOP, "final_msg": FINAL_MSG}})
        end = _loop(st, reports, w, root, prof, temp, seed, resume=resume, max_turns=max_turns,
                    snap_name=os.path.basename(logp)[:-6])
    except BaseException as e:  # noqa: BLE001  v3c: сбой харнесса не теряет лог — пишется error и end
        end = f"forced: harness error: {type(e).__name__}: {e}"[:300]
        try:
            w({"type": "error", "error": f"{type(e).__name__}: {e}"[:1000], "traceback": traceback.format_exc()[-4000:]})
        except Exception:  # noqa: BLE001
            pass
        if not isinstance(e, Exception):
            raise                                       # KeyboardInterrupt / SystemExit: end пишет finally
    finally:
        st["model_sec"] = round(st["model_sec"], 1)
        st["sec_per_turn"] = round(st["model_sec"] / max(1, st["turns"]), 1)
        try:
            w({"type": "end", "reason": end or "forced: interrupted", "stats": st, "reports": reports})
        finally:
            log.close()
            release_view(lock)
    print(json.dumps({"log": logp, "reason": end, **st}, ensure_ascii=False))
    return logp


def _loop(st, reports, w, root, prof, temp, seed, resume=None, max_turns=None, snap_name="s"):
    """Цикл сессии -> причина конца. Каждый вызов инструмента обрабатывается под try: исключение -> модели
    'Error: ...', в лог — harness_error с трассой.
    v3b: resume — снимок (SNAPSHOT_DIR) для ветвления: история и счётчики продолжаются с него; max_turns — сколько
    ходов сделать после снимка."""
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": FIRST_USER}]
    seen_cmds = {}                   # команда -> (номер вызова, индекс tool-сообщения)
    tool_msgs = []                   # индексы tool-сообщений в messages по порядку
    tool_meta = {}                   # v3b: индекс tool-сообщения -> (номер вызова, команда или имя инструмента)
    cleared = set()
    last_prompt, pending = 0, 0      # pending = оценка токенов, добавленных после последнего ответа
    warned_ctx = warned_steps = False
    since_report = 0
    final_left, final_why = 0, None
    end = None
    turn0 = 0
    if resume:
        messages = resume["messages"]
        seen_cmds = {k: tuple(v) for k, v in resume["seen_cmds"].items()}
        tool_msgs = list(resume["tool_msgs"])
        tool_meta = {int(k): tuple(v) for k, v in resume["tool_meta"].items()}
        cleared = set(resume["cleared"])
        last_prompt, pending = resume["last_prompt"], resume["pending"]
        warned_ctx, warned_steps, since_report = resume["warned_ctx"], resume["warned_steps"], resume["since_report"]
        st.update(resume["st"])
        reports.extend(resume["reports"])
        turn0 = st["turns"]
        w({"type": "resume", "from": resume.get("name"), "turn": turn0, "max_turns": max_turns})

    def snapshot():
        os.makedirs(SNAPSHOT_DIR, exist_ok=True)
        snap = {"name": f"{snap_name}_T{st['turns']}", "messages": messages, "seen_cmds": seen_cmds,
                "tool_msgs": tool_msgs, "tool_meta": tool_meta, "cleared": sorted(cleared),
                "last_prompt": last_prompt, "pending": pending, "warned_ctx": warned_ctx,
                "warned_steps": warned_steps, "since_report": since_report, "st": st, "reports": reports,
                "reads_acc": {r: sorted(v) for r, v in reads_acc.items()}, "scanned_acc": sorted(scanned_acc)}
        path = f"{SNAPSHOT_DIR}/{snap['name']}.json"
        with open(path, "w") as f:
            json.dump(snap, f, ensure_ascii=False)
        w({"type": "note", "text": f"[harness] snapshot {path}"})

    def note_user(text):
        nonlocal pending
        messages.append({"role": "user", "content": text})
        pending += est_tokens(text)
        w({"type": "note", "text": text})

    def stub_for(idx):
        c = messages[idx]["content"]
        call, cmd = tool_meta.get(idx, (None, ""))
        return STUB.format(lines=c.count("\n") + 1, chars=len(c), call=call, cmd=" ".join(str(cmd).split())[:200])

    def clear_old():
        """Старые выводы инструментов -> заглушка (как clear_tool_uses / prune в кодинг-харнессах).
        Чистим пачкой, чтобы префикс-кэш сервера сбрасывался редко. v3b: CLEAR_TO — до какой оценки чистить
        (от старых к новым), CLEAR_AT_LEAST — минимум освобождаемого, иначе история не трогается."""
        nonlocal last_prompt
        plan, freed = [], 0
        est0 = last_prompt + pending
        for idx in (tool_msgs[:-KEEP_RESULTS] if KEEP_RESULTS else tool_msgs):
            if idx in cleared:
                continue
            if CLEAR_TO is not None and est0 - freed <= CLEAR_TO:
                break
            m = messages[idx]
            if len(m["content"]) < 400:
                continue
            stub = stub_for(idx)
            plan.append((idx, stub))
            freed += est_tokens(m["content"]) - est_tokens(stub)
        if not plan or freed < CLEAR_AT_LEAST:
            if plan:
                w({"type": "note", "text": f"[harness] clear skipped: would free ~{freed} < {CLEAR_AT_LEAST}"})
            return 0
        for idx, stub in plan:
            messages[idx]["content"] = stub
            cleared.add(idx)
        last_prompt -= freed
        st["clears"] += 1
        st["cleared_results"] += len(plan)
        w({"type": "note", "text": f"[harness] cleared {len(plan)} old tool outputs, ~{freed} tokens",
           "cleared_calls": [tool_meta.get(i, (None,))[0] for i, _ in plan]})
        return len(plan)

    def compact():
        """A2 «сжатие»: модель пишет сводку; всё до хода, которому принадлежит KEEP_RESULTS-й с конца вывод,
        заменяется одним user-сообщением со сводкой и списком записанных report. Неудача -> обычная очистка."""
        nonlocal last_prompt, pending
        if len(tool_msgs) <= KEEP_RESULTS:
            return 0
        cut = tool_msgs[-KEEP_RESULTS] if KEEP_RESULTS else len(messages)
        while cut > 2 and messages[cut]["role"] != "assistant":
            cut -= 1
        if cut <= 2:
            return clear_old()
        t0 = time.time()
        # S4: без tools префикс шаблона другой -> кэш не берётся (233 с на 45K); те же tools.
        # S8: с tools модель ответила одним вызовом без текста -> tool_choice "none" (воркер держит tools в промпте)
        # и одна повторная просьба, если текста всё равно нет.
        req = [{"role": "user", "content": COMPACT_REQ}]
        summary, r, perr, tries = "", None, None, 0
        for extra in ([], [{"role": "user", "content": "Write the summary now, as plain text."}]):
            tries += 1
            resp, err = chat(messages + req + extra, temp, seed + 100000 + st["turns"] + tries, TOOLS, "none")
            r, perr = (None, err) if err else parse_response(resp)
            summary = ((r or {}).get("content") or "").strip()
            if summary or err:
                break
        dt = time.time() - t0
        st["model_sec"] += dt
        if not summary:
            w({"type": "note", "text": f"[harness] compaction failed ({perr or 'empty summary'}); clearing instead",
               "sec": round(dt, 1)})
            return clear_old()
        st["gen_tokens"] += r["usage"].get("completion_tokens") or 0
        rep_list = "\n".join(f"#{i + 1} ({x['kind']}): {x['observation']}" for i, x in enumerate(reports)) or "(none yet)"
        head = {"role": "user", "content": "[Earlier messages were removed from your context to save space. "
                f"Your summary of them:]\n\n{summary}\n\n[Findings recorded so far with report:]\n{rep_list}"}
        off = cut - 3
        removed_calls = [tool_meta.get(i, (None,))[0] for i in tool_msgs if i < cut]
        tool_msgs[:] = [i - off for i in tool_msgs if i >= cut]
        tm = {i - off: v for i, v in tool_meta.items() if i >= cut}
        tool_meta.clear()
        tool_meta.update(tm)
        sc = {k_: (v[0], v[1] - off) for k_, v in seen_cmds.items() if v[1] >= cut}
        seen_cmds.clear()
        seen_cmds.update(sc)
        cl = {i - off for i in cleared if i >= cut}
        cleared.clear()
        cleared.update(cl)
        messages[:] = messages[:2] + [head] + messages[cut:]
        last_prompt, pending = est_tokens(json.dumps(messages, ensure_ascii=False)), 0
        st["compactions"] += 1
        w({"type": "compact", "turn": st["turns"], "sec": round(dt, 1), "usage": r["usage"],
           "finish_reason": r["finish_reason"], "summary": summary, "summary_had_calls": bool(r["calls"]),
           "removed_calls": removed_calls, "removed_msgs": cut - 2, "est_after": last_prompt, "tries": tries,
           "reports_listed": len(reports)})
        return len(removed_calls)

    def enter_final(why):
        nonlocal final_left, final_why
        final_left, final_why = FINAL_TURNS, why
        if FINAL_MSG is not None:                       # 29.10: одно сообщение для всех причин
            note_user(FINAL_MSG)
            return
        head = (f"You have used all {STEP_BUDGET} tool calls." if why == "step budget" else
                f"You have used all {BASH_LIMIT} bash calls." if why == "bash limit" else
                f"The context is almost full (about {last_prompt + pending} of {CTX} tokens).")
        note_user(head + " bash is no longer available. Record each finding you can support with report now "
                  "(several report calls in one reply are fine), then call finish. Example: " + REPORT_EXAMPLE)

    hyps = []                        # 29.10 (R1): реестр гипотез
    rejected_now = [0]               # A1: отклонённых report в текущем ответе
    accepted_now = [0]               # A1: принятых report в текущем ответе
    pend = [False]                   # A1: в финале есть отклонённый report, после которого не было хода с принятым без отказов
    fix_left = [FINAL_FIX_TURNS]     # A1: сколько ходов финала ещё можно не расходовать из-за отклонённого report
    repeat_run = [0]                 # 29.10 (REPEAT_STOP): повторов подряд (сбрасывает любой вызов, кроме повтора)
    loop_hit = [False]               # 29.10: повторов подряд стало REPEAT_STOP -> финал в конце хода

    reads_acc = {r: set(v) for r, v in (resume or {}).get("reads_acc", {}).items()}
    scanned_acc = set((resume or {}).get("scanned_acc", []))

    def note_reads(cmd, info, res):
        """Учёт открытых файлов трасс (trace_reads) -> res['reads'] и счётчики st; модели не показывается."""
        try:
            rd = trace_reads(cmd, root, info.get("parsed"))
        except Exception:  # noqa: BLE001
            res["reads_error"] = traceback.format_exc()[-1000:]
            return
        if rd["read"] or rd["scanned"] or rd["unresolved"]:
            res["reads"] = rd
        for r, fs in rd["read"].items():
            reads_acc.setdefault(r, set()).update(fs)
        scanned_acc.update(rd["scanned"])
        st["read_unresolved_calls"] = st.get("read_unresolved_calls", 0) + bool(rd["unresolved"])
        tr_ = sorted(r for r, fs in reads_acc.items() if _is_trace_read(fs))
        st["traces_read"] = tr_
        st["n_traces_read"] = len(tr_)
        st["runs_opened"] = sorted(reads_acc)
        st["traces_scanned_only"] = sorted(scanned_acc - set(reads_acc))
        st["step_files_read"] = sum(sum(bool(STEP_FILE_RE.match(f)) for f in fs) for fs in reads_acc.values())
        st["traces_read_exact"] = sorted(r for r, fs in reads_acc.items() if _is_trace_read([f for f in fs if f[:1] != "?"]))

    def do_call(name_, raw, res):
        """Один вызов инструмента -> (текст для модели, finish ли)."""
        nonlocal since_report
        try:
            args = json.loads(raw) if raw else {}
            if not isinstance(args, dict):
                raise ValueError("arguments must be a JSON object")
        except Exception as e:  # noqa: BLE001
            st["bad_call"] += 1
            res["format_fail"] = "bad_json"
            return f"Error: could not parse the arguments as JSON ({e}). Call the tool again with valid JSON arguments.", False
        if name_ == "runs" and RUNS_TOOL and RUNS_MODE in ("tool", "both"):
            a = args.get("args", "")
            a = a if isinstance(a, str) else " ".join(map(str, a)) if isinstance(a, list) else ""
            a = a.strip()
            if a.startswith("runs "):
                a = a[5:]
            name_, args = "bash", {"command": ("runs " + a).strip(), "_via_runs_tool": True}
            res["via_runs_tool"] = True
        if name_ == "bash" and final_left:
            st["bad_call"] += 1
            res["format_fail"] = "bash_in_final"
            return "Error: bash is no longer available. Record your findings with report, then call finish.", False
        if name_ == "bash" and BASH_LIMIT and st["bash_calls"] >= BASH_LIMIT:
            st["bash_over_limit"] += 1
            res["format_fail"] = "bash_over_limit"
            return (f"Error: all {BASH_LIMIT} bash calls are used; this command was not run. Record your findings "
                    "with report, then call finish."), False
        if name_ == "bash":
            st["bash_calls"] += 1
            cmd = args.get("command")
            if not isinstance(cmd, str) or not cmd.strip():
                st["bad_call"] += 1
                res["format_fail"] = "missing_arg"
                return "Error: bash needs a 'command' string.", False
            key = " ".join(cmd.split())
            prev = seen_cmds.get(key)
            if prev and prev[1] not in cleared:
                st["repeats"] += 1
                res["repeat"] = True
                if REPEAT_STOP:                         # 29.10: не исполняется; REPEAT_STOP подряд -> финал
                    repeat_run[0] += 1
                    res["repeat_run"] = repeat_run[0]
                    st["repeat_run_max"] = max(st["repeat_run_max"], repeat_run[0])
                    if repeat_run[0] >= REPEAT_STOP:
                        loop_hit[0] = True
                    return REPEAT_MSG, False
                old = messages[prev[1]]["content"] if prev[1] < len(messages) else ""
                head = old if len(old) <= 600 else old[:600] + f"\n[... {len(old)} characters in all]"
                return (f"This is the same command as tool call {prev[0]}, and the files have not changed, so the "
                        f"result is the same:\n{head}\n\nTo learn something new, run a different command (another "
                        "file, another range with sed -n, another pattern), or record what you have found."), False
            st["bash"] += 1
            seen_cmds[key] = (st["tool_calls"], len(messages))
            ok, out, full, info, tr = bash_output(cmd, root, prof)
            if not ok:
                st["denied"] += 1
            else:
                note_reads(cmd, info, res)
            st["truncated"] += tr
            # v3: в лог — начало вывода и длина (вывод может быть до MAX_CAPTURE байт)
            res.update(ok=ok, full_chars=len(full), truncated=tr, capped=info["capped"],
                       timed_out=info["timed_out"], output_head=full[:LOG_HEAD])
            return out, False
        if name_ == "report":
            kind = args.get("kind")
            obs = args.get("observation")
            ev = args.get("evidence")
            if isinstance(ev, str):
                ev = ([ev.strip()] if ev.strip() else []) if EVIDENCE_MODE == "free" else \
                    [x.strip() for x in re.split(r"[,\n]", ev) if x.strip()]   # free: цитату по запятым не резать
            errs = []
            if kind not in ("problem", "pattern", "meta"):
                errs.append("kind must be one of problem, pattern, meta")
            if not isinstance(obs, str) or not obs.strip():
                errs.append("observation must be a non-empty string")
            elif "\x00" in obs:
                errs.append("observation contains a NUL byte (\\x00)")
            ev_errs, ev_norm = (check_evidence_free if EVIDENCE_MODE == "free" else check_evidence)(ev, root)
            errs += ev_errs
            if errs:
                st["reports_rejected"] += 1
                res["rejected"] = errs
                rejected_now[0] += 1
                if final_left:
                    st["final_rejected"] += 1
                    pend[0] = True
                hint = ("Each evidence item is free-form text: a short quote with the path of its file, 'path:line', "
                        "'path:start-end' or a path; a path in it must exist in the directory. "
                        if EVIDENCE_MODE == "free" else
                        "Each evidence item is 'path:line' or 'path:start-end' (line numbers as grep -n or "
                        "sed -n show them); a file of up to 80 lines may be given by its path alone. ")
                return ("Error: report not recorded.\n- " + "\n- ".join(errs) + "\n" + hint +
                        "Fix it and call report again, e.g. " + REPORT_EXAMPLE), False
            st["reports_ok"] += 1
            accepted_now[0] += 1
            st["first_report_call"] = st["first_report_call"] or st["tool_calls"]
            reports.append({"kind": kind, "observation": obs, "evidence": ev_norm, "evidence_raw": ev,
                            "step": st["tool_calls"], "final": bool(final_left)})
            res["recorded"] = len(reports)
            since_report = -1
            return f"Recorded finding #{len(reports)}.", False
        if name_ == "note" and NOTES and not final_left:
            txt = args.get("text")
            if not isinstance(txt, str) or not txt.strip():
                st["bad_call"] += 1
                res["format_fail"] = "missing_arg"
                return "Error: note needs a 'text' string.", False
            st["notes"] += 1
            return "Noted.", False
        if name_ == "hypothesis" and HYPOTHESES:
            cl = args.get("claim")
            if not isinstance(cl, str) or not cl.strip():
                st["bad_call"] += 1
                res["format_fail"] = "missing_arg"
                return "Error: hypothesis needs a 'claim' string.", False
            hyps.append({"id": f"H{len(hyps) + 1}", "claim": cl.strip(), "confirms_if": str(args.get("confirms_if", "")),
                         "refutes_if": str(args.get("refutes_if", "")), "result": "open"})
            st["hypotheses"] = len(hyps)
            return f"{hyps[-1]['id']} recorded.", False
        if name_ == "verdict" and HYPOTHESES:
            hid = str(args.get("id", "")).strip().upper()
            rr = args.get("result")
            h = next((x for x in hyps if x["id"] == hid), None)
            if h is None or rr not in ("held", "refuted", "unclear"):
                st["bad_call"] += 1
                res["format_fail"] = "bad_verdict"
                return ("Error: verdict needs an existing id (" + (", ".join(x["id"] for x in hyps) or "none yet")
                        + ") and result held, refuted or unclear."), False
            h["result"], h["why"] = rr, str(args.get("why", ""))
            st["verdicts_" + rr] = st.get("verdicts_" + rr, 0) + 1
            return f"{hid}: {rr}.", False
        if name_ == "finish":
            if final_left and pend[0] and fix_left[0] > 0:
                st["finish_deferred"] += 1
                res["deferred"] = True
                return ("Not finished yet: a report call was not recorded (the reason is in its result). Fix it "
                        "and call report again, then call finish."), False
            return "Finished.", True
        st["bad_call"] += 1
        res["format_fail"] = "unknown_tool"
        return (f"Error: unknown tool '{name_}'. Tools: " +
                ("report, finish." if final_left else ", ".join(x["function"]["name"] for x in TOOLS) + ".")), False

    while end is None:
        if max_turns is not None and st["turns"] - turn0 >= max_turns:
            end = f"fork: {max_turns} turns done"
            break
        if CLEAR_AT is not None and last_prompt + pending >= CLEAR_AT and not final_left:
            if SNAPSHOT_DIR and not resume:
                snapshot()
            compact() if COMPACT else clear_old()
        est = last_prompt + pending
        if est >= CTX - MAX_GEN - 1500:
            end = "forced: context estimate too large to send"
            break
        if est >= HARD_AT and not final_left:
            enter_final("context")
            est = last_prompt + pending
        t0 = time.time()
        r = perr = None
        for attempt in range(API_RETRIES + 1):
            resp, err = chat(messages, temp, seed + st["turns"], FINAL_TOOLS if final_left else TOOLS)
            if err:
                break
            r, perr = parse_response(resp)
            if r:
                break
            w({"type": "api_error", "turn": st["turns"] + 1, "attempt": attempt + 1, "error": perr,
               "response": json.dumps(resp, ensure_ascii=False)[:2000]})
            if attempt < API_RETRIES:
                st["api_retries"] += 1
                time.sleep(API_RETRY_SEC)
        dt = time.time() - t0
        st["model_sec"] += dt
        st["turns"] += 1
        st["final_turns"] += bool(final_left)
        if err:
            w({"type": "turn", "i": st["turns"], "sec": round(dt, 1), "error": err, "est_prompt": est})
            end = f"forced: model call failed: {err[:200]}"
            break
        if not r:
            w({"type": "turn", "i": st["turns"], "sec": round(dt, 1), "error": f"bad response: {perr}",
               "est_prompt": est})
            end = f"forced: bad API response after {API_RETRIES + 1} attempts: {perr}"
            break
        u = r["usage"]
        last_prompt = (u.get("prompt_tokens") or est) + (u.get("completion_tokens") or 0)
        pending = 0
        st["gen_tokens"] += u.get("completion_tokens") or 0
        st["max_prompt"] = max(st["max_prompt"], u.get("prompt_tokens") or 0)
        if r["finish_reason"] == "length":
            st["length_stops"] += 1
        calls = r["calls"]
        rec = {"type": "turn", "i": st["turns"], "sec": round(dt, 1), "usage": u, "est_prompt": est,
               "final": bool(final_left), "finish_reason": r["finish_reason"], "content": r["content"], "reasoning": r.get("reasoning"),
               "tool_calls": [{"name": c["function"]["name"], "arguments": c["function"]["arguments"]} for c in calls],
               "results": []}
        if r["bad"]:
            rec["malformed_calls"] = r["bad"]
            st["bad_call"] += r["bad"]
        amsg = {"role": "assistant", "content": r["content"] or ""}
        if calls:
            amsg["tool_calls"] = [{"id": c["id"] or f"call_{st['turns']}_{j}", "type": "function",
                                   "function": {"name": c["function"]["name"], "arguments": c["function"]["arguments"]}}
                                  for j, c in enumerate(calls)]
        messages.append(amsg)
        finished = False
        rejected_now[0] = accepted_now[0] = 0
        if not calls:
            st["no_call"] += 1
            txt = r["content"] or ""
            kind = "malformed" if (r["bad"] or "<tool_call>" in txt or "<function=" in txt) else "none"
            note = ("Your reply contained a tool call the system could not parse. Call a tool again using the "
                    "tool-calling format." if kind == "malformed" else
                    "Your reply contained no tool call. Continue with bash, record findings with report, or call finish."
                    if not final_left else "Your reply contained no tool call. Call report for each supported finding, then finish.")
            rec["format_fail"] = kind
            note_user(note)
            w(rec)
            if st["no_call"] >= 6 and not final_left:
                end = "forced: too many replies without a tool call"
        for c in amsg.get("tool_calls", []):
            name_, raw = c["function"]["name"], c["function"]["arguments"]
            st["tool_calls"] += 1
            res = {"name": name_, "arguments": raw}
            try:
                if (SAY_FIRST and not final_left and name_ in ("bash", "runs") and st.get("bash_calls", 0) > 0
                        and len((r["content"] or "").strip()) < SAY_FIRST):
                    st["say_rejected"] = st.get("say_rejected", 0) + 1
                    res["say_rejected"] = True
                    out, finished = SAY_MSG, False
                else:
                    out, finished = do_call(name_, raw, res)
            except Exception as e:  # noqa: BLE001  v3c: ответ модели не роняет харнесс
                st["harness_errors"] += 1
                res["harness_error"] = traceback.format_exc()[-2000:]
                out, finished = f"Error: {type(e).__name__}: {str(e)[:300]}", False
            since_report += 1
            if REPEAT_STOP and not res.get("repeat"):
                repeat_run[0] = 0
            # приписки цикла: контекст, шаги, давно не было report
            left = STEP_BUDGET - st["tool_calls"]
            est_now = last_prompt + pending + est_tokens(out)
            if not finished and not final_left:
                if WARN_AT is not None and est_now >= WARN_AT and not warned_ctx:
                    warned_ctx = True
                    out += (f"\n\n[note: about {est_now} of {CTX} context tokens used. Start wrapping up: report the "
                            "findings you can support, then call finish.]")
                if left <= STEP_BUDGET - STEP_WARN and not warned_steps:
                    warned_steps = True
                    out += f"\n\n[note: {left} tool calls left. Report what you have found, then call finish.]"
                elif REMIND_EVERY and since_report and since_report % REMIND_EVERY == 0:
                    st["reminders"] += 1
                    out += (f"\n\n[note: {since_report} tool calls since your last recorded finding; {left} of "
                            f"{STEP_BUDGET} calls left. If something you checked is supported by lines you have read, "
                            "record it with report now.]")
            if HYPOTHESES and hyps and name_ in ("bash", "runs") and not final_left:
                out += "\n\n[hypotheses: " + "; ".join(
                    f"{x['id']} {x['result']}: {x['claim'][:110]}" for x in hyps[-8:]) + "]"
            res["shown"] = out if res.get("output_head") != out else "(= output_head)"
            rec["results"].append(res)
            tool_meta[len(messages)] = (st["tool_calls"], _cmd_of(name_, raw))
            tool_msgs.append(len(messages))
            messages.append({"role": "tool", "tool_call_id": c["id"], "content": out})
            pending += est_tokens(out) + 10
            if finished:
                break
        if calls:
            w(rec)
        if end:
            break
        if finished:
            end = "finish"
        elif final_left:
            if accepted_now[0] and not rejected_now[0]:
                pend[0] = False
            if pend[0] and fix_left[0] > 0:
                fix_left[0] -= 1                        # A1: отклонённый report ещё не исправлен — финал не сокращается
                st["final_fix_used"] += 1
                w({"type": "note", "text": f"[harness] final turn not counted: a rejected report is not fixed yet "
                   f"({rejected_now[0]} rejected this turn); {fix_left[0]} such turns left"})
            else:
                final_left -= 1
            if not final_left:
                end = f"forced: {final_why} (final turns used)"
        elif loop_hit[0]:
            loop_hit[0] = False
            st["loop_final"] += 1
            enter_final("loop")
        elif st["tool_calls"] >= STEP_BUDGET:
            enter_final("step budget")
        elif BASH_LIMIT and st["bash_calls"] >= BASH_LIMIT:
            enter_final("bash limit")
    return end


def _cmd_of(name_, raw):
    if name_ != "bash":
        return name_
    try:
        return json.loads(raw).get("command", "")
    except Exception:  # noqa: BLE001
        return ""


def main():
    global LAYOUT
    ap = argparse.ArgumentParser()
    ap.add_argument("--view", default=LAYOUT)
    ap.add_argument("--runs", help="проваленные run через запятую (иначе --k случайных с --seed)")
    ap.add_argument("--k", type=int, default=3)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--temp", type=float, default=0.6)
    ap.add_argument("--policy", default="compact", choices=sorted(POLICIES))   # A2: выбрана compact (JOURNAL.md §4)
    ap.add_argument("--set", action="append", default=[], help="KEY=JSON поверх политики")
    ap.add_argument("--tag", default="t")
    ap.add_argument("--dry", action="store_true", help="только выбор трасс и промпт")
    a = ap.parse_args()
    LAYOUT = os.path.realpath(os.path.expanduser(a.view))
    apply_policy(a.policy, {k: json.loads(v) for k, v in (x.split("=", 1) for x in a.set)})
    runs = [int(x) for x in a.runs.split(",")] if a.runs else None
    if a.dry:
        print(json.dumps(select("rand", a.k, a.seed, runs), ensure_ascii=False))
        print(SYSTEM)
        print(json.dumps(TOOLS, indent=1))
        return
    session("rand", a.k, a.seed, a.temp, a.tag, runs=runs)


if __name__ == "__main__":
    main()
