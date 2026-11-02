"""Вход сессии: принятые report исследователя и первые сообщения ролей."""
import glob
import json
import os

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
        lines = cited(r["evidence"], root) if root else []
        if lines:
            part += "\nCited log lines, as the file has them:\n" + "\n".join(lines)
        parts.append(part)
    return "\n\n".join(parts)


def first_user_editor_obs(reports, root=None):
    return (observations_text(reports, root) + "\n\nChange src/ so that the agent fails fewer tasks. Call finish "
            "when you are done.")


def first_user_proposer(reports):
    return (observations_text(reports) + "\n\nPropose fixes to the harness for these observations. Call finish when "
            "you are done.")


def first_user_editor_fix(props):
    parts = ["Proposed fixes for the harness, from a study of the agent's failed runs:"]
    for i, p in enumerate(props, 1):
        parts.append(f"## Proposal {i}\nProblem: {p['problem']}\nFix: {p['fix']}")
    return "\n\n".join(parts) + "\n\nChange src/ so that the agent fails fewer tasks. Call finish when you are done."
