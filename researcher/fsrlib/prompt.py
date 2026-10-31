"""Системный промпт и инструменты: строки промпта, build_system, build_tools; SYSTEM, TOOLS, FINAL_TOOLS —
под текущую политику (пересобирает apply_policy)."""
from . import cfg as C


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
    return EX_EV_FREE if C.EVIDENCE_MODE == "free" else EX_EV

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
SAY_MSG = ("Not run. In the reply itself, before the call, write what you saw "
           "in the last output and what this command will check; then call it.")
JOB = "Your job: find the weaknesses of the harness — in its prompts or its code — that make runs fail, and show how each one leads to failure."
CAUSE_JOB = ("Your job: for each failed run, find out what actually happened and why the task failed, as the "
             "environment's responses show it (what the agent says about its own progress is a claim to check against "
             "them); then find what in the harness — its prompts or its code — made that failure likely or could have "
             "prevented it. A failure in which the harness had no part is a finding too: say so.")
CAUSE_FIRST = ("Investigate the failed runs in this repository: what went wrong in each, and what in the harness, if "
               "anything, made them fail. Call finish when you are done.")
LIMIT_LINE = ("bash can be called N times; after that only report and finish remain, for a few turns, and the "
              "session ends")   # A1: вместо «the session ends after STEP_BUDGET tool calls»


def build_system():
    ctx = "compact" if C.COMPACT else "notes" if C.NOTES else "none" if C.CLEAR_AT is None else "stub"
    s = SYSTEM_T.replace("NOTE_TOOL", NOTE_TOOL_LINE if C.NOTES else "").replace("CTX_LINE", CTX_LINE[ctx])
    if C.EVIDENCE_MODE == "free":
        assert EV_STRICT_SYS in s
        s = s.replace(EV_STRICT_SYS, EV_FREE_SYS)
    if C.RUNS_TOOL:     # 29.10 v2: runs — в Tools, пример начала сессии вместо строки про jq
        assert JQ_LINE in s and BASH_TAIL in s and TARGETED in s and BSD_LINE in s
        if C.RUNS_MODE == "bash":
            s = (s.replace(JQ_LINE, RUNS_EXAMPLE).replace(BASH_TAIL, BASH_TAIL_RUNS).replace(TARGETED, TARGETED_RUNS)
                 .replace(BSD_LINE, RUNS_LINE + "\n" + BSD_LINE))
        else:         # tool / both: runs(args) — отдельный инструмент; both — ещё и программа в bash
            line = RUNS_TOOL_LINE + (RUNS_BOTH_NOTE if C.RUNS_MODE == "both" else "")
            s = (s.replace(JQ_LINE, RUNS_TOOL_EXAMPLE).replace(BASH_TAIL, BASH_TAIL_RUNS)
                 .replace(TARGETED, TARGETED_RUNS.replace("runs show N A-B", "runs show N A-B"))
                 .replace(BSD_LINE, BSD_LINE + "\n" + line))
    if C.DIARY:
        assert RECORD_LINE + " " in s
        s = s.replace(RECORD_LINE + " ", DIARY_LINE + "\n- ")
    if C.HYPOTHESES:
        fl = "- finish(): end the investigation."
        assert fl in s
        s = s.replace(fl, HYP_LINE + "\n" + fl)
    if C.TAXONOMY == "trail":
        w_ = "- Work like an engineer debugging a system"
        i_ = s.index(w_)
        j_ = s.index("\n", i_)
        s = s[:j_ + 1] + TRAIL_LINE + "\n" + s[j_ + 1:]
    if C.CHECKLIST:
        w_ = "- Work like an engineer debugging a system"
        i_ = s.index(w_)
        j_ = s.index("\n", i_)
        s = s[:j_ + 1] + CHECK_LINE + "\n" + s[j_ + 1:]
    if C.SAY_FIRST:
        w_ = "- Work like an engineer debugging a system"
        i_ = s.index(w_)
        j_ = s.index("\n", i_)
        s = s[:j_ + 1] + SAY_LINE + "\n" + s[j_ + 1:]
    if C.CAUSE:         # 31.10 (аудит R3, R4): цель — что произошло по ответам среды, потом роль харнесса
        assert JOB in s
        s = s.replace(JOB, CAUSE_JOB)
    if C.PYTHON:
        assert BSD_LINE in s
        s = s.replace(BSD_LINE, BSD_LINE + "\n" + PYTHON_LINE)
    progs = sorted(C.ALLOWED - ({"runs"} if C.RUNS_TOOL and C.RUNS_MODE == "tool" else set()))
    return (s.replace("PROGRAMS", ", ".join(progs)).replace("OUT_CHARS", str(C.OUT_CHARS))
            .replace("the session ends after STEP_BUDGET tool calls", LIMIT_LINE.replace("N", str(C.BASH_LIMIT))
                     if C.BASH_LIMIT else "the session ends after STEP_BUDGET tool calls")
            .replace("STEP_BUDGET", str(C.STEP_BUDGET)).replace("EX_EV", ex_ev()))


def first_user():
    return CAUSE_FIRST if C.CAUSE else FIRST_USER


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
    if C.EVIDENCE_MODE == "free":
        t[1]["function"]["parameters"]["properties"]["evidence"]["description"] = EV_FREE_DESC
    if C.HYPOTHESES:
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
    if C.RUNS_TOOL and C.RUNS_MODE in ("tool", "both"):
        t.insert(1, {"type": "function", "function": {
            "name": "runs", "description": "Read the run logs message by message. args as on a command line: '' lists "
            "runs; 'show N 40-45', 'show N --tail 6', 'grep -i PATTERN N M'; 'help' for all options.",
            "parameters": {"type": "object", "properties": {"args": {"type": "string", "description": "The arguments"}},
                           "required": ["args"]}}})
    if C.NOTES:
        t.insert(1, {"type": "function", "function": {
            "name": "note", "description": "Write down something you will need later: a fact with the path:line it "
            "comes from, a hypothesis, what you have checked. Notes stay in your context; command outputs do not.",
            "parameters": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}}})
    return t


TOOLS = build_tools()
FINAL_TOOLS = [x for x in TOOLS if x["function"]["name"] in ("report", "finish")]
