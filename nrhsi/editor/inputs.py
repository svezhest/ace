"""Вход сессии: принятые report исследователя и первые сообщения ролей."""
import ast
import glob
import json
import os
import re
import subprocess

from . import cfg as C
from ..researcher import evidence as EV

CITE_CHARS = 400         # --cite: символов строки лога на цитату
CITE_LINES = 6           # --cite: строк на наблюдение


def input_log(tag):
    ps = [p for p in glob.glob(f"{C.RLOGS}/*_{tag}.jsonl")]
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
        if r.get("check"):                   # 3.11, исследователь EVIDENCE_MODE=check: команда и её вывод
            out[-1].update(check=r["check"], check_out=r.get("check_out", ""))
    return out


def review_root(tag):
    """Вид, который читал исследователь (его logs/run_N.jsonl), по строке meta лога сессии; None — нет на диске."""
    log = input_log(tag)
    meta = json.loads(open(log).readline())
    root = os.path.join(os.path.dirname(os.path.dirname(log)), "views", meta.get("view", ""))
    return root if os.path.isdir(f"{root}/logs") else None


def cited(evidence, root):
    """--cite (3.11): строки logs/run_N.jsonl, на которые ссылается evidence, как они есть в файле (обрезаны)."""
    out = []
    for e in evidence:
        ml = EV.EV_LIST_RE.match(e)
        m = None if ml else EV.CITE_RE.match(e)
        mh = EV.EV_HEAD_RE.match(e)
        path = (ml or m or mh).group(1) if (ml or m or mh) else None
        if not path or not EV.RUN_LOG_RE.match(os.path.normpath(path)) or not os.path.isfile(f"{root}/{path}"):
            continue
        lines = EV._read_log(f"{root}/{path}")
        if ml or m:
            nums = ([int(x) for x in ml.group(2).split(",")] if ml else
                    list(range(int(m.group(2)), int(m.group(3) or m.group(2)) + 1)))
        else:
            q = e[mh.end():].strip().strip("'\"`“”«»").strip()
            nums = EV._quote_lines(q, lines)[:2] if len(q) >= EV.QUOTE_MIN else []
        for x in nums:
            if 1 <= x <= len(lines) and len(out) < CITE_LINES:
                s = lines[x - 1]
                out.append(f"{path}:{x}: " + (s if len(s) <= CITE_CHARS else s[:CITE_CHARS] + " ..."))
    return out


def observations_text(reports, root=None):
    parts = ["Observations from a study of the agent's failed runs (references to logs/ point to the runs, which "
             "are not in this copy):"]
    for i, r in enumerate(reports, 1):
        ev = "\n".join(f"- {x}" for x in r["evidence"]) or "- (none)"
        part = f"## Observation {i} ({r['kind']})\n{r['observation']}\nEvidence:\n{ev}"
        if "check" in r:
            o, cap = r["check_out"], CITE_CHARS * CITE_LINES
            part = (f"## Observation {i} ({r['kind']})\n{r['observation']}\nCheck: {r['check']}\nIt printed:\n"
                    + (o if len(o) <= cap else o[:cap] + f"\n[... {len(o)} characters in all]"))
        lines = cited(r["evidence"], root) if root else []
        if lines:
            part += "\nCited log lines, as the file has them:\n" + "\n".join(lines)
        parts.append(part)
    return "\n\n".join(parts)


OBS_TAIL = "\n\nChange src/ so that the agent fails fewer tasks. Call finish when you are done."


def first_user_editor_obs(reports, root=None):
    return observations_text(reports, root) + OBS_TAIL


def first_user_editor_text(path, src=None):
    """3.11, проба потолка формата: вместо блока наблюдений — готовый текст из файла, как есть.
    5.11 --given-code: src — src/ вида; под текстом — код, на который он ссылается (given_code)."""
    t = open(path).read().rstrip()
    return t + (given_code(t, src) if src else "") + OBS_TAIL


REF = re.compile(r"(src/[\w.-]+)?:(\d+)(?:-(\d+))?")
GIVEN_PAD_MD, GIVEN_PAD_PY, GIVEN_MAX_DEF = 4, 8, 60    # строк вокруг ссылки в .md / вне функции в .py; длиннее — не целиком


def cited_ranges(text):
    """Ссылки src/F:a-b и короткие :a (на последний названный файл) -> {F: [(a, b)]}."""
    out, cur = {}, None
    for m in REF.finditer(text):
        if m.group(1):
            cur = m.group(1)
        if cur is None:
            continue
        a = int(m.group(2))
        out.setdefault(cur, []).append((a, int(m.group(3) or a)))
    return out


def widen_py(code, a, b):
    """Строки a..b -> наименьшая функция, что их содержит (если не длиннее GIVEN_MAX_DEF), иначе ±GIVEN_PAD_PY."""
    best = None
    for n in ast.walk(ast.parse(code)):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            lo = min([n.lineno] + [d.lineno for d in n.decorator_list])
            if lo <= a and b <= n.end_lineno and n.end_lineno - lo + 1 <= GIVEN_MAX_DEF:
                if best is None or n.end_lineno - lo < best[1] - best[0]:
                    best = (lo, n.end_lineno)
    return best or (a - GIVEN_PAD_PY, b + GIVEN_PAD_PY)


def given_code(text, src):
    """Код src/, на который ссылается текст наблюдения, как он есть: функции целиком, иначе строки вокруг ссылки."""
    parts = []
    for f, rs in cited_ranges(text).items():
        path = f"{src}/{f[4:]}"
        if not os.path.exists(path):
            continue
        code = open(path).read()
        lines = code.splitlines()
        wide = sorted(widen_py(code, a, b) if f.endswith(".py") else (a - GIVEN_PAD_MD, b + GIVEN_PAD_MD) for a, b in rs)
        merged = []
        for a, b in wide:
            a, b = max(1, a), min(len(lines), b)
            if merged and a <= merged[-1][1] + 1:
                merged[-1] = (merged[-1][0], max(merged[-1][1], b))
            else:
                merged.append((a, b))
        lang = "python" if f.endswith(".py") else ""
        for a, b in merged:
            parts.append(f"{f}, lines {a}-{b}:\n```{lang}\n" + "\n".join(lines[a - 1:b]) + "\n```")
    if not parts:
        return ""
    return "\n\n## The code these references point to, as it is now in src/\n\n" + "\n\n".join(parts)


def first_user_proposer(reports):
    return (observations_text(reports) + "\n\nPropose fixes to the harness for these observations. Call finish when "
            "you are done.")


def src_diff(x, y):
    """diff -ruN src/ двух узлов, пути — src/FILE."""
    r = subprocess.run(["diff", "-ruN", "-x", "__pycache__", f"{x}/src", f"{y}/src"], capture_output=True, text=True)
    return r.stdout.replace(f"{x}/src/", "src/").replace(f"{y}/src/", "src/")


def first_user_merge(view):
    """--arm merge (3.11): изменения a и b против общего предка и файлы с конфликтом — по merge.json вида (editor/merge3.py)."""
    m = json.load(open(f"{view}/merge.json"))
    conf = [f"src/{f}" for f, s in m["files"].items() if s.startswith("conflict")]
    parts = [f"## Changes in {k} against the original\n```diff\n{src_diff(m['base'], m[k]).rstrip()}\n```" for k in ("a", "b")]
    tail = ("Files where a and b changed the same lines, with git conflict markers (<<<<<<< a, =======, >>>>>>> b): "
            + ", ".join(conf) + "." if conf else "No file has conflicts: a and b changed different lines.")
    return ("\n\n".join(parts) + "\n\n" + tail + "\n\nMake src/ one working harness with what each version adds. "
            "Call finish when you are done.")


def first_user_editor_fix(props):
    parts = ["Proposed fixes for the harness, from a study of the agent's failed runs:"]
    for i, p in enumerate(props, 1):
        parts.append(f"## Proposal {i}\nProblem: {p['problem']}\nFix: {p['fix']}")
    return "\n\n".join(parts) + "\n\nChange src/ so that the agent fails fewer tasks. Call finish when you are done."
