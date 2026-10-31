"""Сессия роли: запись meta, цикл ходов до finish или принудительного конца, запись end."""
import traceback

from .cfg import F
from . import cfg as C
from . import state as R
from . import turn as TU
from . import phase as PH


def meta(run, system, first_user):
    return {"type": "meta", "role": run.role, "system": system, "first_user": first_user, "seed": run.seed,
            "temperature": F.TEMP, "stand": F.STAND,
            "root": run.root, "tools": [t["function"]["name"] for t in run.tools],
            "limits": {"bash_limit": C.BASH_LIMIT, "step_budget": C.STEP_BUDGET, "final_turns": C.FINAL_TURNS,
                       "hard_at": C.HARD_AT, "out_chars": F.OUT_CHARS, "max_gen": F.MAX_GEN}}


def loop(run):
    """Ходы до конца -> причина конца."""
    end = None
    while end is None:
        est = run.est()
        if est >= C.HARD_AT and not run.final_left:
            PH.enter_final(run, "context")
        if est >= F.CTX - F.MAX_GEN - 1500:
            return "forced: context estimate too large to send"
        end = TU.turn(run, est)
    return end


def run_session(role, system, first_user, root, prof, seed, log_path, n_obs=0):
    """role: editor | proposer. -> (причина конца, st, items) — items: правки (editor) или предложения (proposer)."""
    run = R.Run(role, system, first_user, root, prof, seed, log_path, n_obs)
    run.w(meta(run, system, first_user))
    end = None
    try:
        end = loop(run)
    except BaseException as e:  # noqa: BLE001
        end = f"forced: harness error: {type(e).__name__}: {e}"[:300]
        run.w({"type": "error", "traceback": traceback.format_exc()[-4000:]})
        if not isinstance(e, Exception):
            raise
    finally:
        run.st["model_sec"] = round(run.st["model_sec"], 1)
        run.w({"type": "end", "reason": end or "forced: interrupted", "stats": run.st, "items": run.items})
        run.log.close()
    return end, run.st, run.items
