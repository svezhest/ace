"""Финальные ходы: вход (лимит bash, бюджет вызовов, окно) и расход их по концу хода."""
from . import cfg as C
from . import lint as LI


def enter_final(run, why):
    run.final_left, run.final_why = C.FINAL_TURNS, why
    head = (f"You have used all {C.BASH_LIMIT} bash calls." if why == "bash limit" else
            f"You have used all {C.STEP_BUDGET} tool calls." if why == "step budget" else
            "The context is almost full.")
    lint_ = LI.lint_changed(run.root)
    run.note_user(f"{head} bash is no longer available. Edits are still applied and checked after each one; "
                  f"{C.FINAL_TURNS} turns remain, then the session ends." + (f"\n\n{lint_}" if lint_ else ""))


def after_turn(run, finished):
    """Конец хода -> причина конца сессии или None."""
    if finished:
        return "finish"
    if run.final_left:
        run.final_left -= 1
        if not run.final_left:
            return f"forced: {run.final_why} (final turns used)"
    elif run.st["bash_calls"] >= C.BASH_LIMIT:
        enter_final(run, "bash limit")
    elif run.st["tool_calls"] >= C.STEP_BUDGET:
        enter_final(run, "step budget")
    return None
