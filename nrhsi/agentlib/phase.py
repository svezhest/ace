"""Финальные ходы: вход (лимит bash, повторы подряд, край окна) и расход их по концу хода."""
from . import cfg as C


def enter_final(run):
    run.final_left, run.fix_left = C.FINAL_TURNS, C.FINAL_FIX_TURNS
    run.say(run.final_msg)


def after_turn(run, finished):
    """Конец хода -> причина конца сессии или None."""
    if finished:
        return "finish"
    if run.final_left:
        if run.rejected and run.fix_left:
            run.fix_left -= 1                # ход с отклонённым вызовом роли не считается
        else:
            run.final_left -= 1
            if not run.final_left:
                return "forced: final turns used"
    elif run.repeats >= C.REPEAT_STOP or run.bash_calls >= run.bash_limit:
        enter_final(run)
    return None
