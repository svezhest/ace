"""Редактор харнесса на 9B (фаза B1): вход — report исследователя, трасс нет; правки — edit(path, old, new).

Два плеча входа:
  obs — наблюдения исследователя (kind, observation, evidence) как есть -> редактор;
  fix — промежуточный шаг (та же 9B, чтение src/, без трасс) превращает наблюдения в варианты исправлений
        словами (propose) -> редактор получает только варианты.
Механика bash (песочница, белый список, обрезка вывода, python3, «/» = корень копии) и транспорт — researcher/fsr.py.
Рабочий каталог сессии: work/<tag>/ = README.md вида без раздела logs/ + копия src/ (edit пишет только сюда)
+ tests/smoke.py (smoke/<bench>.py): прогон src/harness.py на заглушке среды и модели, запуск python3 tests/smoke.py.

python editor.py --bench alf --input a7k5ef --arm obs --seed 1 --tag b1_alf_a7k5ef_obs
python editor.py --bench alf --input a7k5ef --arm fix --seed 1 --tag b1_alf_a7k5ef_fix
python editor.py ... --dry      # напечатать промпты и первые сообщения, без модели
"""
import argparse
import glob
import hashlib
import json
import re
import os
import shutil
import subprocess
import sys
import time
import traceback

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.expanduser("~/Projects/nrhsi/researcher"))
import fsr as F  # noqa: E402

# 30.10: механика bash — fsr исследователя (политика final: python3, heredoc), «/» = корень копии.
F.apply_policy("final", {"RUNS_TOOL": False})
SMOKE_README = ("- `tests/smoke.py` — a smoke test: runs src/harness.py with a stub environment and a stub model (not the "
                "benchmark) and prints what the harness adds to the conversation after which model reply, or the error. "
                "Run it with `python3 tests/smoke.py`.\n")

VIEWS = {"alf": os.path.expanduser("~/Projects/nrhsi/alfworld/view"),
         "app": os.path.expanduser("~/Projects/nrhsi/appworld/view")}
RLOGS = os.path.expanduser("~/Projects/nrhsi/researcher/logs")

BASH_LIMIT = 25          # вызовов bash; потом — финальные ходы
STEP_BUDGET = 60         # всех вызовов инструментов
FINAL_TURNS = 3
HARD_AT = 54000          # оценка prompt -> финальные ходы
MAX_NO_CALL = 6
SHOW_CONTEXT = 2         # строк вокруг изменённого места в ответе edit
SHOW_MAX = 80

# ---------------------------------------------------------------- промпты

BASH_TOOL_LINES = """- bash(command): a read-only shell in the working directory. Programs: PROGRAMS. Pipes, ';', '&&', '||', $(...), for/while loops and if work. Nothing can be written with it. Output longer than OUT_CHARS characters is truncated, so read big files in parts (sed -n '40,90p' FILE, head, tail) and search with grep -n.
- The shell is bash 3.2 with macOS/BSD utilities: GNU-only options are missing (use grep -E, not grep -P; no find -printf).
PYTHON_LINE"""

REPO_LINE = ("You are working in a copy of a repository that holds the harness of an AI agent: the prompts and "
             "the code that run the agent on tasks. README.md describes the layout; the harness is in src/. This directory is everything there is to "
             "read: the agent's runs and the benchmark are not here.")

EDIT_TOOL_LINE = ("- edit(path, old_string, new_string): replace old_string with new_string in the file at path, a "
                  "file in src/ (src/bridge.py is not part of the harness, see README.md). old_string must be copied "
                  "exactly from the file as it is now, spaces and line breaks included, and occur in it exactly once; "
                  "include enough of the neighbouring lines to make it unique. To add text, put an existing "
                  "neighbouring line in old_string and repeat it in new_string together with the addition. To write "
                  "into an empty file or to create a new file in src/, give an empty old_string. Each edit is "
                  "applied at once and you see the changed lines; an edit that cannot be applied leaves the file as "
                  "it was and tells you why.")

ARM_EDITOR = {
    "obs": ("The agent's failed runs were studied by a colleague; their observations are in the first message. The "
            "runs themselves are not in this copy.",
            "Each observation that points to a weakness of the harness is a candidate for a change. An observation "
            "may also be inaccurate, or point to something the harness cannot change; what it says about src/ you "
            "can check by reading src/."),
    "fix": ("A colleague studied the agent's failed runs and proposed fixes for the harness; the proposals are in the "
            "first message. The runs themselves are not in this copy.",
            "Make the proposed fixes you judge sound; where several proposals address the same weakness in "
            "different ways, choose the way you judge best, or combine them. What a proposal says about src/ you "
            "can check by reading src/."),
}

EDITOR_T = f"""{REPO_LINE}

ARM_CONTEXT

Your goal: change src/ so that the agent fails fewer tasks. ARM_GOAL The same harness runs on every task the agent gets, so aim for changes that help on tasks in general. A change may be to a prompt or to the code.

# Tools
{BASH_TOOL_LINES}
{EDIT_TOOL_LINE}
- finish(): end the session when your changes are done.

# How to work
- Read the part of src/ a change touches before you edit it, and keep intact what the rest of the harness relies on: README.md and the comments at the top of the code describe how the parts fit together.
- Check each change: run python3 tests/smoke.py, and read the changed lines together with the code that calls or uses them.
- bash can be called BASH_LIMIT times; after that only edit and finish remain, for a few turns, and the session ends.
- Call finish when you are done."""

PROPOSER_T = f"""{REPO_LINE} Nothing in it can be changed.

The agent's failed runs were studied by a colleague; their observations are in the first message. The runs themselves are not in this copy.

Your goal: propose fixes to the harness that would make the agent fail fewer tasks. For each observation that points to a weakness of the harness, find where in src/ it comes from and describe how src/ could be changed to remove it. When there are different reasonable ways to fix it (in a prompt or in the code, at one place or another), record each way as a separate proposal. An observation may be inaccurate, or point to something the harness cannot change; what it says about src/ you can check by reading src/. The same harness runs on every task the agent gets, so aim for fixes that help on tasks in general. An engineer will make the changes from your proposals alone, without the observations, so each proposal should be complete on its own.

# Tools
{BASH_TOOL_LINES}
- propose(problem, fix, observations): record one proposed fix. problem: what goes wrong for the agent and what in src/ causes it. fix: where to change src/ (the file and the part of it) and what the change is, in words precise enough for another engineer to make it. observations: the numbers of the observations it rests on.
- finish(): end the session when your proposals are recorded.

# How to work
- Record each proposal with propose as soon as you have settled on it; several propose calls in one reply are fine.
- bash can be called BASH_LIMIT times; after that only propose and finish remain, for a few turns, and the session ends.
- Call finish when you are done."""


def fill(t, arm=None):
    if arm:
        ctx, goal = ARM_EDITOR[arm]
        t = t.replace("ARM_CONTEXT", ctx).replace("ARM_GOAL", goal)
    t = t.replace("PYTHON_LINE", F.PYTHON_LINE)
    return (t.replace("PROGRAMS", ", ".join(sorted(F.ALLOWED))).replace("OUT_CHARS", str(F.OUT_CHARS))
            .replace("BASH_LIMIT", str(BASH_LIMIT)))


CHECK_LINE = ("- Check each change: run python3 tests/smoke.py, and read the changed lines together with the code that "
              "calls or uses them.")
PREDICT_LINE = ("- Check each change: before you run python3 tests/smoke.py, write down what you expect it to print "
                "after your change (which messages, after which replies, how the run ends); after it runs, compare "
                "the output with what you wrote, line by line, and say where they differ before you go on. Read the "
                "changed lines together with the code that calls or uses them.")


BASH_SCHEMA = {"type": "function", "function": {
    "name": "bash", "description": "Run a read-only shell command in the working directory. Pipes, ';', '&&', '||', "
    "$(...), for/while loops and if work; nothing can be written. Long output is truncated: use grep -n, sed -n 'a,bp', head, tail.",
    "parameters": {"type": "object", "properties": {"command": {"type": "string", "description": "The command line"}},
                   "required": ["command"]}}}
EDIT_SCHEMA = {"type": "function", "function": {
    "name": "edit", "description": "Replace old_string with new_string in a file in src/. old_string must match the "
    "file's current text exactly (spaces, line breaks) and occur in it exactly once; an empty old_string writes into "
    "an empty file or creates a new one.",
    "parameters": {"type": "object", "properties": {
        "path": {"type": "string", "description": "The file to change, e.g. src/FILE"},
        "old_string": {"type": "string", "description": "Exact text from the file to replace"},
        "new_string": {"type": "string", "description": "The text to put in its place"}},
        "required": ["path", "old_string", "new_string"]}}}
PROPOSE_SCHEMA = {"type": "function", "function": {
    "name": "propose", "description": "Record one proposed fix to the harness.",
    "parameters": {"type": "object", "properties": {
        "problem": {"type": "string", "description": "What goes wrong for the agent and what in src/ causes it"},
        "fix": {"type": "string", "description": "Where to change src/ and what the change is, in words"},
        "observations": {"type": "array", "items": {"type": "integer"},
                         "description": "Numbers of the observations this rests on"}},
        "required": ["problem", "fix", "observations"]}}}
FINISH_SCHEMA = {"type": "function", "function": {
    "name": "finish", "description": "End the session.", "parameters": {"type": "object", "properties": {}}}}


# ---------------------------------------------------------------- вход

def input_log(tag):
    ps = [p for p in glob.glob(f"{RLOGS}/*_{tag}.jsonl")]
    assert len(ps) == 1, (tag, ps)
    return ps[0]


def load_reports(tag):
    """Принятые report сессии исследователя как есть: kind, observation, evidence (то, что написала модель)."""
    recs = [json.loads(l) for l in open(input_log(tag))]
    end = [r for r in recs if r.get("type") == "end"][-1]
    out = []
    for r in end["reports"]:
        ev = r.get("evidence_raw")
        if not isinstance(ev, list):
            ev = r.get("evidence") or []
        out.append({"kind": r["kind"], "observation": r["observation"], "evidence": [str(x) for x in ev]})
    return out


def observations_text(reports):
    parts = ["Observations from a study of the agent's failed runs (references to logs/ point to the runs, which "
             "are not in this copy):"]
    for i, r in enumerate(reports, 1):
        ev = "\n".join(f"- {x}" for x in r["evidence"]) or "- (none)"
        parts.append(f"## Observation {i} ({r['kind']})\n{r['observation']}\nEvidence:\n{ev}")
    return "\n\n".join(parts)


def first_user_editor_obs(reports):
    return (observations_text(reports) + "\n\nChange src/ so that the agent fails fewer tasks. Call finish when you "
            "are done.")


def first_user_proposer(reports):
    return (observations_text(reports) + "\n\nPropose fixes to the harness for these observations. Call finish when "
            "you are done.")


def first_user_editor_fix(props):
    parts = ["Proposed fixes for the harness, from a study of the agent's failed runs:"]
    for i, p in enumerate(props, 1):
        parts.append(f"## Proposal {i}\nProblem: {p['problem']}\nFix: {p['fix']}")
    return "\n\n".join(parts) + "\n\nChange src/ so that the agent fails fewer tasks. Call finish when you are done."


# ---------------------------------------------------------------- рабочий каталог

def readme_without_logs(text):
    out = []
    for line in text.splitlines(keepends=True):
        if line.startswith("- `logs/`"):
            break
        out.append(line)
    return "".join(out).rstrip("\n") + "\n"


def build_work(bench, tag, smoke=True):
    v = f"{HERE}/work/{tag}"
    if os.path.lexists(v):
        shutil.rmtree(v)
    os.makedirs(v)
    with open(f"{VIEWS[bench]}/README.md") as f:
        readme = readme_without_logs(f.read())
    if smoke:
        readme += SMOKE_README
    with open(f"{v}/README.md", "w") as f:
        f.write(readme)
    shutil.copytree(f"{VIEWS[bench]}/src", f"{v}/src", ignore=shutil.ignore_patterns("__pycache__"))
    if smoke:
        os.makedirs(f"{v}/tests")
        shutil.copy(f"{HERE}/smoke/{bench}.py", f"{v}/tests/smoke.py")
    for p in glob.glob(f"{v}/src/*"):
        assert os.stat(p).st_nlink == 1, p          # копия, не жёсткая ссылка
    return os.path.realpath(v)


def make_profile(root, tag):
    p = f"{HERE}/work/.sb_{tag}_{os.getpid()}.sb"
    with open(p, "w") as f:
        f.write(F.profile_text(root))
    F._PROFILES.append(p)
    return p


def tree_hash(d):
    h = hashlib.sha256()
    for p in sorted(glob.glob(f"{d}/**/*", recursive=True)):
        if os.path.isfile(p) and "__pycache__" not in p:
            h.update(os.path.relpath(p, d).encode() + b"\0" + open(p, "rb").read() + b"\0")
    return h.hexdigest()[:16]


# ---------------------------------------------------------------- edit

def numbered(lines, a, b):
    return "".join(f"{i + 1:>6}\t{lines[i]}" for i in range(a, b))


def do_edit(args, root, st):
    """-> (текст для модели, запись в лог). Применяет одну замену в root/src/..., либо объясняет отказ."""
    path, old, new = args.get("path"), args.get("old_string"), args.get("new_string")
    rec = {"path": path, "old": old, "new": new}

    def fail(kind, msg):
        rec["fail"] = kind
        st["edit_fail"][kind] = st["edit_fail"].get(kind, 0) + 1
        return f"Error: edit not applied. {msg}", rec

    if not isinstance(path, str) or not isinstance(old, str) or not isinstance(new, str):
        return fail("args", "path, old_string and new_string must all be strings.")
    p = path.strip()
    if p.startswith(root + os.sep):
        p = os.path.relpath(p, root)
    rel = os.path.normpath(p)
    rec["rel"] = rel
    full = os.path.realpath(os.path.join(root, rel))
    srcd = os.path.join(root, "src")
    if not full.startswith(srcd + os.sep) or "__pycache__" in rel:
        return fail("path", f"{path} is not a file in src/; only files in src/ can be changed.")
    if os.path.relpath(full, srcd) == "bridge.py":
        return fail("bridge", "src/bridge.py is the connection to the benchmark, not part of the harness "
                              "(README.md); it cannot be changed.")
    exists = os.path.isfile(full)
    if os.path.exists(full) and not exists:
        return fail("path", f"{rel} is not a file.")
    text = open(full, encoding="utf-8").read() if exists else None
    if old == new:
        return fail("same", "old_string and new_string are the same, so there is nothing to change.")
    if old == "":
        if text:
            return fail("empty_old", f"old_string is empty, but {rel} is not empty; copy the text to replace from it.")
        if not exists and not os.path.isdir(os.path.dirname(full)):
            return fail("path", f"the directory of {rel} does not exist.")
        newtext = new
        a_line = 0
    else:
        if not exists:
            return fail("missing", f"{rel} does not exist.")
        n = text.count(old)
        if n == 0:
            return fail("not_found", f"old_string does not occur in {rel}; it must be copied exactly from the "
                                     "file's current text.")
        if n > 1:
            starts, i = [], text.find(old)
            while i >= 0:
                starts.append(text.count("\n", 0, i) + 1)
                i = text.find(old, i + 1)
            return fail("multiple", f"old_string occurs {n} times in {rel} (starting at lines "
                                    f"{', '.join(map(str, starts[:10]))}); include more of the neighbouring text so "
                                    "that it occurs once.")
        i = text.find(old)
        newtext = text[:i] + new + text[i + len(old):]
        a_line = text.count("\n", 0, i)
    if rel.endswith(".py"):
        try:
            compile(newtext, rel, "exec")
        except SyntaxError as e:
            rec["syntax"] = f"{e.msg} (line {e.lineno})"
            return fail("syntax", f"With this change {rel} would not parse as Python (SyntaxError: {e.msg}, line "
                                  f"{e.lineno}); the file is unchanged.")
    tmp = full + ".edit_tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(newtext)
    os.replace(tmp, full)
    st["edits_applied"] += 1
    rec["applied"] = True
    rec["created"] = not exists
    lines = newtext.splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    b_line = a_line + max(1, new.count("\n") + (0 if new.endswith("\n") else 1)) if new else a_line
    lo, hi = max(0, a_line - SHOW_CONTEXT), min(len(lines), b_line + SHOW_CONTEXT)
    if hi - lo > SHOW_MAX:
        shown = numbered(lines, lo, lo + SHOW_MAX) + f"[... {hi - lo - SHOW_MAX} more lines]\n"
    else:
        shown = numbered(lines, lo, hi)
    what = (f"Applied: {rel} created." if not exists else
            f"Applied: {rel}, the new text is at lines {a_line + 1}-{max(a_line + 1, b_line)}." if new else
            f"Applied: text removed from {rel} at line {a_line + 1}.")
    note = lint_note(text if exists else "", newtext, rel)
    rec["lint"] = note.strip() or None
    return (f"{what} Lines {lo + 1}-{hi} now read:\n{shown}" if lines else f"{what} The file is now empty.") + note, rec


def lint(text, rel):
    """pyflakes по тексту файла -> [(строка, сообщение)]."""
    import io
    sys.path.insert(0, f"{HERE}/lint")
    from pyflakes import api, reporter
    out = io.StringIO()
    api.check(text, rel, reporter.Reporter(out, out))
    res = []
    for ln in out.getvalue().splitlines():
        m = re.match(rf"{re.escape(rel)}:(\d+):(?:\d+:?)?\s*(.*)", ln)
        if m:
            res.append((int(m.group(1)), m.group(2)))
    return res


def lint_note(old, new, rel):
    """Предупреждения pyflakes, которых не было до правки (сравнение по тексту сообщения)."""
    if not rel.endswith(".py"):
        return ""
    before = {msg for _, msg in lint(old, rel)} if old else set()
    fresh = [(n, msg) for n, msg in lint(new, rel) if msg not in before]
    if not fresh:
        return ""
    return ("\npyflakes on " + rel + " after this change:\n" +
            "".join(f"  line {n}: {msg}\n" for n, msg in fresh[:10]))


# ---------------------------------------------------------------- цикл

def run_session(role, system, first_user, root, prof, seed, log_path, n_obs=0):
    """role: editor | proposer. -> (причина конца, st, items) — items: правки (editor) или предложения (proposer)."""
    tools = [BASH_SCHEMA, EDIT_SCHEMA if role == "editor" else PROPOSE_SCHEMA, FINISH_SCHEMA]
    final_tools = tools[1:]
    act = "edit" if role == "editor" else "propose"
    messages = [{"role": "system", "content": system}, {"role": "user", "content": first_user}]
    st = {"turns": 0, "tool_calls": 0, "bash_calls": 0, "denied": 0, "repeats": 0, "truncated": 0, "no_call": 0,
          "bad_call": 0, "max_prompt": 0, "gen_tokens": 0, "model_sec": 0.0, "final_turns": 0, "length_stops": 0,
          "edits_attempted": 0, "edits_applied": 0, "edit_fail": {}, "proposals": 0, "proposals_rejected": 0}
    items = []
    seen = {}
    final_left, final_why = 0, None
    last_prompt = pending = 0
    log = open(log_path, "w", encoding="utf-8", errors="backslashreplace")

    def w(rec):
        log.write(json.dumps(rec, ensure_ascii=False) + "\n")
        log.flush()

    def note_user(text):
        nonlocal pending
        messages.append({"role": "user", "content": text})
        pending += F.est_tokens(text) + 10
        w({"type": "note", "text": text})

    def enter_final(why):
        nonlocal final_left, final_why
        final_left, final_why = FINAL_TURNS, why
        head = (f"You have used all {BASH_LIMIT} bash calls." if why == "bash limit" else
                f"You have used all {STEP_BUDGET} tool calls." if why == "step budget" else
                "The context is almost full.")
        tail = ("Make the edits you have settled on with edit now (several edit calls in one reply are fine), then "
                "call finish." if role == "editor" else
                "Record the proposals you have settled on with propose now (several propose calls in one reply are "
                "fine), then call finish.")
        note_user(f"{head} bash is no longer available. {tail}")

    def do_call(name, raw, res):
        try:
            args = json.loads(raw) if raw else {}
            if not isinstance(args, dict):
                raise ValueError("arguments must be a JSON object")
        except Exception as e:  # noqa: BLE001
            st["bad_call"] += 1
            res["format_fail"] = "bad_json"
            return f"Error: could not parse the arguments as JSON ({e}). Call the tool again with valid JSON arguments.", False
        if name == "bash":
            if final_left or st["bash_calls"] >= BASH_LIMIT:
                st["bad_call"] += 1
                res["format_fail"] = "bash_unavailable"
                return f"Error: bash is no longer available; this command was not run. Use {act}, then call finish.", False
            cmd = args.get("command")
            st["bash_calls"] += 1
            if not isinstance(cmd, str) or not cmd.strip():
                st["bad_call"] += 1
                return "Error: bash needs a 'command' string.", False
            key = " ".join(cmd.split())
            if key in seen:
                st["repeats"] += 1
                res["repeat"] = True
                old = seen[key][1]
                head = old if len(old) <= 600 else old[:600] + f"\n[... {len(old)} characters in all]"
                return (f"This is the same command as tool call {seen[key][0]}, and the files have not changed since, "
                        f"so the result is the same:\n{head}"), False
            ok, out, full, info, tr = F.bash_output(cmd, root, prof)
            st["denied"] += not ok
            st["truncated"] += tr
            seen[key] = (st["tool_calls"], out)
            res.update(ok=ok, full_chars=len(full), truncated=tr)
            return out, False
        if name == "edit" and role == "editor":
            st["edits_attempted"] += 1
            text, rec = do_edit(args, root, st)
            rec["call"] = st["tool_calls"]
            rec["final"] = bool(final_left)
            items.append(rec)
            res["edit"] = {k: rec.get(k) for k in ("rel", "fail", "applied", "syntax")}
            if rec.get("applied"):
                seen.clear()                     # файлы изменились: повтор чтения разрешён
            return text, False
        if name == "propose" and role == "proposer":
            p, fx, ob = args.get("problem"), args.get("fix"), args.get("observations")
            errs = []
            if not isinstance(p, str) or not p.strip():
                errs.append("problem must be a non-empty string")
            if not isinstance(fx, str) or not fx.strip():
                errs.append("fix must be a non-empty string")
            if isinstance(ob, (int, str)):
                ob = [ob]
            try:
                ob = [int(x) for x in (ob or [])]
            except (TypeError, ValueError):
                ob = None
            if ob is None or any(not 1 <= x <= n_obs for x in ob):
                errs.append(f"observations must be a list of observation numbers from 1 to {n_obs}")
            if errs:
                st["proposals_rejected"] += 1
                res["rejected"] = errs
                return "Error: proposal not recorded: " + "; ".join(errs) + ".", False
            st["proposals"] += 1
            items.append({"problem": p.strip(), "fix": fx.strip(), "observations": ob, "call": st["tool_calls"],
                          "final": bool(final_left)})
            return f"Proposal {st['proposals']} recorded.", False
        if name == "finish":
            return "Finished.", True
        st["bad_call"] += 1
        res["format_fail"] = "unknown_tool"
        names = [t["function"]["name"] for t in (final_tools if final_left else tools)]
        return f"Error: unknown tool '{name}'. Tools: {', '.join(names)}.", False

    w({"type": "meta", "role": role, "system": system, "first_user": first_user, "seed": seed, "temperature": F.TEMP,
       "stand": F.STAND,
       "root": root, "tools": [t["function"]["name"] for t in tools],
       "limits": {"bash_limit": BASH_LIMIT, "step_budget": STEP_BUDGET, "final_turns": FINAL_TURNS,
                  "hard_at": HARD_AT, "out_chars": F.OUT_CHARS, "max_gen": F.MAX_GEN}})
    end = None
    try:
        while end is None:
            est = last_prompt + pending
            if est >= HARD_AT and not final_left:
                enter_final("context")
            if est >= F.CTX - F.MAX_GEN - 1500:
                end = "forced: context estimate too large to send"
                break
            t0 = time.time()
            r = perr = err = None
            for attempt in range(F.API_RETRIES + 1):
                resp, err = F.chat(messages, F.TEMP, seed + st["turns"], final_tools if final_left else tools)
                if err:
                    break
                r, perr = F.parse_response(resp)
                if r:
                    break
                w({"type": "api_error", "attempt": attempt + 1, "error": perr})
                time.sleep(F.API_RETRY_SEC)
            dt = time.time() - t0
            st["model_sec"] += dt
            st["turns"] += 1
            st["final_turns"] += bool(final_left)
            if err or not r:
                w({"type": "turn", "i": st["turns"], "error": err or perr})
                end = f"forced: model call failed: {(err or perr)[:200]}"
                break
            u = r["usage"]
            last_prompt = (u.get("prompt_tokens") or est) + (u.get("completion_tokens") or 0)
            pending = 0
            st["max_prompt"] = max(st["max_prompt"], u.get("prompt_tokens") or 0)
            st["gen_tokens"] += u.get("completion_tokens") or 0
            st["length_stops"] += r["finish_reason"] == "length"
            calls = r["calls"]
            rec = {"type": "turn", "i": st["turns"], "sec": round(dt, 1), "usage": u, "final": bool(final_left),
                   "finish_reason": r["finish_reason"], "content": r["content"], "reasoning": r.get("reasoning"),
                   "tool_calls": [{"name": c["function"]["name"], "arguments": c["function"]["arguments"]}
                                  for c in calls], "results": []}
            amsg = {"role": "assistant", "content": r["content"] or ""}
            if calls:
                amsg["tool_calls"] = [{"id": c["id"] or f"call_{st['turns']}_{j}", "type": "function",
                                       "function": c["function"]} for j, c in enumerate(calls)]
            messages.append(amsg)
            finished = False
            if not calls:
                st["no_call"] += 1
                txt = r["content"] or ""
                malformed = r["bad"] or "<tool_call>" in txt or "<function=" in txt
                w(rec)
                note_user("Your reply contained a tool call the system could not parse. Call a tool again using the "
                          "tool-calling format." if malformed else
                          f"Your reply contained no tool call. Continue with the tools; call finish when you are done.")
                if st["no_call"] >= MAX_NO_CALL:
                    end = "forced: too many replies without a tool call"
            for c in amsg.get("tool_calls", []):
                st["tool_calls"] += 1
                res = {"name": c["function"]["name"]}
                try:
                    out, finished = do_call(c["function"]["name"], c["function"]["arguments"], res)
                except Exception as e:  # noqa: BLE001
                    res["harness_error"] = traceback.format_exc()[-2000:]
                    out, finished = f"Error: {type(e).__name__}: {str(e)[:300]}", False
                res["shown"] = out
                rec["results"].append(res)
                messages.append({"role": "tool", "tool_call_id": c["id"], "content": out})
                pending += F.est_tokens(out) + 10
                if finished:
                    break
            if calls:
                w(rec)
            if end:
                break
            if finished:
                end = "finish"
            elif final_left:
                final_left -= 1
                if not final_left:
                    end = f"forced: {final_why} (final turns used)"
            elif st["bash_calls"] >= BASH_LIMIT:
                enter_final("bash limit")
            elif st["tool_calls"] >= STEP_BUDGET:
                enter_final("step budget")
    except BaseException as e:  # noqa: BLE001
        end = f"forced: harness error: {type(e).__name__}: {e}"[:300]
        w({"type": "error", "traceback": traceback.format_exc()[-4000:]})
        if not isinstance(e, Exception):
            raise
    finally:
        st["model_sec"] = round(st["model_sec"], 1)
        w({"type": "end", "reason": end or "forced: interrupted", "stats": st, "items": items})
        log.close()
    return end, st, items


# ---------------------------------------------------------------- сессия

def diff_src(bench, root):
    r = subprocess.run(["diff", "-ruN", "-x", "__pycache__", f"{VIEWS[bench]}/src", f"{root}/src"],
                       capture_output=True, text=True)
    return r.stdout.replace(VIEWS[bench] + "/", "a/").replace(root + "/", "b/")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bench", choices=list(VIEWS), required=True)
    ap.add_argument("--input", required=True, help="тег сессии исследователя (report на входе)")
    ap.add_argument("--arm", choices=["obs", "fix"], required=True)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--view", help="вид узла (src/ и README.md), по умолчанию — корневой вид бенчмарка")
    ap.add_argument("--predict", action="store_true", help="плечо: перед smoke записать ожидаемый вывод, после — сверить")
    ap.add_argument("--stand", default="default", help="профиль стенда (stands/<имя>.json): модель и генерация")
    a = ap.parse_args()
    if a.view:
        VIEWS[a.bench] = os.path.realpath(os.path.expanduser(a.view))
    if not a.dry:
        F.apply_stand(a.stand)
    reports = load_reports(a.input)
    src_before = tree_hash(f"{VIEWS[a.bench]}/src")
    os.makedirs(f"{HERE}/logs", exist_ok=True)
    os.makedirs(f"{HERE}/out", exist_ok=True)
    summary = {"tag": a.tag, "bench": a.bench, "input": a.input, "arm": a.arm, "seed": a.seed, "view": VIEWS[a.bench], "predict": a.predict, "stand": F.STAND,
               "n_reports": len(reports), "view_src_hash": src_before}
    if a.arm == "fix":
        psys, pfirst = fill(PROPOSER_T), first_user_proposer(reports)
        if a.dry:
            print(psys, "\n-----\n", pfirst, "\n=====")
        else:
            proot = build_work(a.bench, a.tag + "_p", smoke=False)
            pprof = make_profile(proot, a.tag + "_p")
            pend, pst, props = run_session("proposer", psys, pfirst, proot, pprof, a.seed * 1000 + 7,
                                           f"{HERE}/logs/{a.tag}_p.jsonl", n_obs=len(reports))
            assert tree_hash(f"{proot}/src") == src_before, "proposer copy changed"
            summary["proposer"] = {"end": pend, "stats": pst, "n": len(props)}
            print(json.dumps({"proposer": pend, "proposals": len(props), "max_prompt": pst["max_prompt"],
                              "min": round(pst["model_sec"] / 60, 1)}), flush=True)
            if not props:
                summary["editor"] = {"end": "skipped: no proposals"}
                json.dump(summary, open(f"{HERE}/out/{a.tag}.summary.json", "w"), ensure_ascii=False, indent=1)
                return
        first = first_user_editor_fix(props if not a.dry else [{"problem": "<problem>", "fix": "<fix>"}])
    else:
        first = first_user_editor_obs(reports)
    esys = fill(EDITOR_T, a.arm)
    if a.predict:
        esys = esys.replace(CHECK_LINE, PREDICT_LINE)
        assert PREDICT_LINE in esys
    if a.dry:
        print(esys, "\n-----\n", first)
        return
    root = build_work(a.bench, a.tag)
    prof = make_profile(root, a.tag)
    end, st, edits = run_session("editor", esys, first, root, prof, a.seed * 1000 + 11, f"{HERE}/logs/{a.tag}.jsonl")
    assert tree_hash(f"{VIEWS[a.bench]}/src") == src_before, "view src changed!"
    d = diff_src(a.bench, root)
    with open(f"{HERE}/out/{a.tag}.diff", "w") as f:
        f.write(d)
    summary["editor"] = {"end": end, "stats": st, "src_hash_after": tree_hash(f"{root}/src")}
    json.dump(summary, open(f"{HERE}/out/{a.tag}.summary.json", "w"), ensure_ascii=False, indent=1)
    print(json.dumps({"editor": end, "edits": f"{st['edits_applied']}/{st['edits_attempted']}",
                      "fail": st["edit_fail"], "max_prompt": st["max_prompt"],
                      "min": round(st["model_sec"] / 60, 1)}), flush=True)


if __name__ == "__main__":
    main()
