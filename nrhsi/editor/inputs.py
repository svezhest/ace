"""Вход сессии: принятые report исследователя и первые сообщения ролей."""
import glob
import json

from . import cfg as C


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
