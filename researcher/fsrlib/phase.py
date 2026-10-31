"""Финальная фаза: вход (бюджет, лимит bash, окно, петля повторов) и расход её ходов."""
from . import cfg as C
from . import prompt as P


def enter_final(run, why):
    run.final_left, run.final_why = C.FINAL_TURNS, why
    if C.FINAL_MSG is not None:                       # 29.10: одно сообщение для всех причин
        run.note_user(C.FINAL_MSG)
        return
    head = (f"You have used all {C.STEP_BUDGET} tool calls." if why == "step budget" else
            f"You have used all {C.BASH_LIMIT} bash calls." if why == "bash limit" else
            f"The context is almost full (about {run.est()} of {C.CTX} tokens).")
    run.note_user(head + " bash is no longer available. Record each finding you can support with report now "
                  "(several report calls in one reply are fine), then call finish. Example: " + P.REPORT_EXAMPLE)


def after_turn(run, finished):
    """Конец хода -> причина конца или None."""
    st = run.st
    if finished:
        return "finish"
    if run.final_left:
        if run.accepted_now and not run.rejected_now:
            run.pend = False
        if run.pend and run.fix_left > 0:
            run.fix_left -= 1                        # A1: отклонённый report ещё не исправлен — финал не сокращается
            st["final_fix_used"] += 1
            run.w({"type": "note", "text": f"[harness] final turn not counted: a rejected report is not fixed yet "
                   f"({run.rejected_now} rejected this turn); {run.fix_left} such turns left"})
        else:
            run.final_left -= 1
        if not run.final_left:
            return f"forced: {run.final_why} (final turns used)"
    elif run.loop_hit:
        run.loop_hit = False
        st["loop_final"] += 1
        enter_final(run, "loop")
    elif st["tool_calls"] >= C.STEP_BUDGET:
        enter_final(run, "step budget")
    elif C.BASH_LIMIT and st["bash_calls"] >= C.BASH_LIMIT:
        enter_final(run, "bash limit")
    return None
