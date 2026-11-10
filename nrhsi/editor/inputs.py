"""Вход сессии: наблюдения ревьювера (принятые report его сессии или готовый текст) и первое сообщение писателя."""
import glob
import json

from . import cfg as C

CHECK_OUT_CHARS = 2400   # символов вывода команды-проверки наблюдения
TASK = "\n\nChange src/ so that the agent fails fewer tasks."


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


def observations_text(reports):
    parts = ["Observations from a study of the agent's failed runs (references to logs/ point to the runs, which "
             "are not in this copy):"]
    for i, r in enumerate(reports, 1):
        ev = "\n".join(f"- {x}" for x in r["evidence"]) or "- (none)"
        part = f"## Observation {i} ({r['kind']})\n{r['observation']}\nEvidence:\n{ev}"
        if "check" in r:
            o = r["check_out"]
            part = (f"## Observation {i} ({r['kind']})\n{r['observation']}\nCheck: {r['check']}\nIt printed:\n"
                    + (o if len(o) <= CHECK_OUT_CHARS else o[:CHECK_OUT_CHARS] + f"\n[... {len(o)} characters in all]"))
        parts.append(part)
    return "\n\n".join(parts)


def ticket_line(t):
    """Ожидание ревьювера из тикета — абзац в конце наблюдения, перед задачей (6.11; keep — вторая половина, TKK)."""
    rs = t["runs"]
    runs = f"run {rs[0]}" if len(rs) == 1 else "runs " + ", ".join(map(str, rs[:-1])) + f" and {rs[-1]}"
    line = {"control": f"Change expected: control — what the harness code does in {runs} should change, not only the texts the model reads.",
            "prompt": f"Change expected: prompt — the texts the model reads in {runs} should change.",
            "any": f"Change expected: any — {runs} should go differently, through the texts the model reads or through the harness code."}[t["change_expected"]]
    ks = t.get("keep") or []
    if ks:
        kr = f"Run {ks[0]}" if len(ks) == 1 else "Runs " + ", ".join(map(str, ks[:-1])) + f" and {ks[-1]}"
        line += (f" {kr} passed without this change: the goal is that {'it' if len(ks) == 1 else 'they'} still "
                 f"{'goes' if len(ks) == 1 else 'go'} exactly as in the log once the change is in. The check after each "
                 "edit tells you whether each of the two holds.")
    return "\n\n" + line


def first_user(reports=None, text_path=None):
    """Первое сообщение: наблюдения (report сессии ревьювера или готовый текст из файла, как есть), ожидание из тикета, задача."""
    obs = open(text_path).read().rstrip() if text_path else observations_text(reports)
    return obs + (ticket_line(C.TICKET) if C.TICKET else "") + TASK
