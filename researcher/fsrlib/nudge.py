"""Дневник report (31.10): подталкивание записывать находки по ходу, а не в финале. Ступени, от мягкой к жёсткой:
- REMIND_EVERY = n — приписка к выводу каждые n вызовов без report;
- BOUNCE_AFTER = k — после k вызовов без report bash не исполняется, пока не будет report;
- DRAFT_AT = [b, ...] — предотчёт: на b-м bash команды не исполняются, пока не будет report.
Отказ тратит вызов bash (иначе петля без конца, как у SAY_FIRST)."""
from . import cfg as C


def note(run):
    """Приписка к выводу (REMIND_EVERY) или ''."""
    st = run.st
    if not (C.REMIND_EVERY and run.since_report and run.since_report % C.REMIND_EVERY == 0):
        return ""
    st["reminders"] += 1
    left = C.STEP_BUDGET - st["tool_calls"]
    bl = (f"{C.BASH_LIMIT - st['bash_calls']} of {C.BASH_LIMIT} bash calls" if C.BASH_LIMIT
          else f"{left} of {C.STEP_BUDGET} calls")
    return (f"\n\n[note: {run.since_report} calls since your last report; {bl} left. Record with report "
            "what these outputs have shown about why runs fail, or a sharper version of an earlier "
            "finding, together with your next command.]")


def gate(run, name_, res):
    """Перед bash/runs: текст отказа или None (команда исполняется)."""
    if run.final_left or name_ not in ("bash", "runs"):
        return None
    st = run.st
    for b in C.DRAFT_AT or ():
        if st["bash_calls"] >= b and b not in run.drafts:
            run.drafts[b] = len(run.reports)
    due = [b for b, n in run.drafts.items() if n == len(run.reports)]
    if due:
        kind, msg = "draft", (f"Not run: {st['bash_calls']} of {C.BASH_LIMIT} bash calls are used. Before going on, "
                              "record with report each finding you have so far (partial ones count; later reports "
                              "can sharpen them), then run the command again.")
    elif C.BOUNCE_AFTER and run.since_report >= C.BOUNCE_AFTER:
        kind, msg = "bounce", (f"Not run: {run.since_report} calls since your last report. First record with report "
                               "what the outputs so far have shown about why runs fail (a partial finding counts; a "
                               "later report can sharpen it), then run the command again.")
    else:
        return None
    st["nudge_rejected"] = st.get("nudge_rejected", 0) + 1
    st["bash_calls"] += 1
    res["nudge_rejected"] = kind
    return msg
