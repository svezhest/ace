"""Сессия: запись meta, ходы до finish или принудительного конца, запись end; профиль песочницы удаляется."""
import os
import traceback

from . import cfg as C
from . import state as R
from . import turn as TU
from . import phase as PH


def meta(run, system, first_user):
    return {"type": "meta", "system": system, "first_user": first_user,
            "tools": [t["function"]["name"] for t in run.tools], "root": run.root, "seed": run.seed,
            "bash_limit": run.bash_limit}


def loop(run):
    """Ходы до конца -> причина конца."""
    end = None
    while end is None:
        if run.est >= C.HARD_AT and not run.final_left:
            PH.enter_final(run)
        if run.est >= C.CTX - C.MAX_GEN - 1500:
            return "forced: context full"
        end = TU.turn(run)
    return end


def session(system, first_user, role_tools, handle, root, log_path, bash_limit, final_msg, seed=1):
    """role_tools — схемы инструментов роли; handle(name, args) -> (текст для модели, принят ли вызов).
    Пишет log_path (jsonl: meta, turn..., end) и возвращает причину конца."""
    run = R.Run(system, first_user, role_tools, handle, root, log_path, bash_limit, final_msg, seed)
    run.w(meta(run, system, first_user))
    end = None
    try:
        end = loop(run)
    except Exception as e:  # noqa: BLE001
        end = f"forced: {type(e).__name__}: {e}"[:300]
        run.w({"type": "error", "traceback": traceback.format_exc()[-4000:]})
    finally:
        run.w({"type": "end", "reason": end or "forced: interrupted", "turns": run.turns, "bash_calls": run.bash_calls})
        run.log.close()
        os.unlink(run.prof)
    return end
