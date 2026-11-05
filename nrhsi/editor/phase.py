"""Финальные ходы: вход (лимит bash, бюджет вызовов, окно) и расход их по концу хода."""
from . import cfg as C
from . import lint as LI


def enter_final(run, why):
    run.final_left, run.final_why = C.FINAL_TURNS, why
    head = (f"You have used all {run.bash_limit} bash calls." if why == "bash limit" else
            f"You have used all {C.STEP_BUDGET} tool calls." if why == "step budget" else
            "The context is almost full.")
    tail = ("Edits can no longer be checked, so they are not applied: call finish." if run.role == "editor" and C.CHECKED else
            "Make the edits you have settled on with edit now (several edit calls in one reply are fine), then "
            "call finish." if run.role == "editor" else
            "Record the proposals you have settled on with propose now (several propose calls in one reply are "
            "fine), then call finish.")
    lint_ = LI.lint_changed(run.root) if run.role == "editor" else ""
    run.note_user(f"{head} bash is no longer available. {tail}" + (f"\n\n{lint_}" if lint_ else ""))


def after_turn(run, finished):
    """Конец хода -> причина конца сессии или None."""
    if finished:
        return "finish"
    if run.final_left:
        run.final_left -= 1
        if not run.final_left:
            return f"forced: {run.final_why} (final turns used)"
    elif run.st["bash_calls"] >= run.bash_limit and C.STAGES and not run.stage2:
        run.stage2, run.bash_limit = True, run.bash_limit + C.STAGES[1]
        run.note_user(f"You have used the {C.STAGES[0]} bash calls for reading, so the check part starts: make your "
                      f"edits; you have {C.STAGES[1]} bash calls left to check them.")
    elif run.st["bash_calls"] >= run.bash_limit:
        enter_final(run, "bash limit")
    elif run.st["tool_calls"] >= C.STEP_BUDGET:
        enter_final(run, "step budget")
    elif C.GOAL_K and not run.goal_sent and run.st["bash_calls"] >= C.BASH_LIMIT - C.GOAL_K:
        run.goal_sent = True
        checks = "python3 tests/smoke.py and python3 tests/rerun.py" if C.RERUN else "python3 tests/smoke.py"
        from . import work as WK
        checks = WK.tt(checks)
        run.note_user(f"{C.BASH_LIMIT - run.st['bash_calls']} bash calls are left. Goal now: check your latest edits "
                      f"with {checks}.")
    return None
