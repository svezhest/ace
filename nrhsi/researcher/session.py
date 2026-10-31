"""Сессия: session (лог, мета, конец), _loop (цикл ходов), main (CLI)."""
import argparse
import json
import os
import traceback

from . import cfg as C
from . import prompt as P
from . import views as V
from . import sandbox as S
from . import model as M
from . import policy as PO
from . import state as R
from . import context as CX
from . import turn as TU
from . import phase as PH


# ---------------------------------------------------------------- цикл


def session(mode, k, seed, temp, tag, resume=None, max_turns=None, runs=None):
    tids, sel = V.select(mode, k, seed, runs)
    name = f"r{'-'.join(map(str, tids))}_{C.POLICY}_s{seed}"
    # v3c: вид и профиль уникальны на сессию (tag в имени; занят живой сессией — ещё и _p<pid>)
    vname, lock = V.claim_view(f"{name}_{tag}")
    try:
        root = V.build_view(vname, tids)
        prof = S.sandbox_profile(root)
        os.makedirs(f"{C.HERE}/logs", exist_ok=True)
        suffix = vname[len(f"{name}_{tag}"):]
        logp = f"{C.HERE}/logs/{name}_{tag}{suffix}.jsonl"
        log = open(logp, "w", encoding="utf-8", errors="backslashreplace")   # v3c: одиночный суррогат не роняет запись
    except BaseException:
        V.release_view(lock)
        raise

    def w(rec):
        log.write(json.dumps(rec, ensure_ascii=False) + "\n")
        log.flush()

    st = {"turns": 0, "tool_calls": 0, "bash": 0, "reports_ok": 0, "reports_rejected": 0, "no_call": 0,
          "bad_call": 0, "repeats": 0, "denied": 0, "truncated": 0, "gen_tokens": 0, "max_prompt": 0,
          "model_sec": 0.0, "length_stops": 0, "clears": 0, "cleared_results": 0, "reminders": 0,
          "final_turns": 0, "first_report_call": None, "api_retries": 0, "harness_errors": 0,
          "traces_read": [], "n_traces_read": 0, "traces_seen": {}, "traces_read_exact": [], "runs_opened": [], "traces_scanned_only": [], "step_files_read": 0,
          "read_unresolved_calls": 0, "notes": 0, "compactions": 0,
          "bash_calls": 0, "bash_over_limit": 0, "final_rejected": 0, "final_fix_used": 0, "finish_deferred": 0,
          "repeat_run_max": 0, "loop_final": 0}
    reports = []
    end = None
    try:
        w({"type": "meta", "version": 3, "mechanics": "v3b-view", "policy": C.POLICY, "layout": C.LAYOUT,
           "tools": [x["function"]["name"] for x in P.TOOLS], "notes_tool": C.NOTES, "compact": C.COMPACT,
           "compact_req": P.COMPACT_REQ if C.COMPACT else None, "read_counter": 1, "variant": C.VARIANT, "mode": mode, "k": k, "seed": seed, "temperature": temp, "stand": C.STAND,
           "runs": tids, "selection": sel, "view": vname, "system": P.SYSTEM, "first_user": P.first_user(), "limits": {
               "ctx": C.CTX, "max_gen": C.MAX_GEN, "warn_at": C.WARN_AT, "hard_at": C.HARD_AT, "clear_at": C.CLEAR_AT,
               "keep_results": C.KEEP_RESULTS, "step_budget": C.STEP_BUDGET, "remind_every": C.REMIND_EVERY, "bounce_after": C.BOUNCE_AFTER, "draft_at": C.DRAFT_AT, "bounce_charge": C.BOUNCE_CHARGE, "bounce_text": C.BOUNCE_TEXT,
               "final_turns": C.FINAL_TURNS, "out_chars": C.OUT_CHARS, "cmd_timeout": C.CMD_TIMEOUT,
               "max_capture": C.MAX_CAPTURE, "log_head": C.LOG_HEAD, "max_cmd": C.MAX_CMD, "max_depth": C.MAX_DEPTH,
               "api_retries": M.API_RETRIES, "clear_to": C.CLEAR_TO, "clear_at_least": C.CLEAR_AT_LEAST, "stub": C.STUB,
               "evidence_mode": C.EVIDENCE_MODE, "trace_mode": C.TRACE_MODE,
               "bash_limit": C.BASH_LIMIT, "final_fix_turns": C.FINAL_FIX_TURNS, "python": C.PYTHON,
               "runs_tool": C.RUNS_TOOL, "runs_format": C.RUNS_FORMAT, "runs_mode": C.RUNS_MODE, "say_first": C.SAY_FIRST, "cause": C.CAUSE, "checklist": C.CHECKLIST, "taxonomy": C.TAXONOMY, "diary": C.DIARY, "hypotheses": C.HYPOTHESES, "thinking": C.THINKING, "think_budget": C.THINK_BUDGET, "repeat_stop": C.REPEAT_STOP, "final_msg": C.FINAL_MSG}})
        end = _loop(st, reports, w, root, prof, temp, seed, resume=resume, max_turns=max_turns,
                    snap_name=os.path.basename(logp)[:-6])
    except BaseException as e:  # noqa: BLE001  v3c: сбой харнесса не теряет лог — пишется error и end
        end = f"forced: harness error: {type(e).__name__}: {e}"[:300]
        try:
            w({"type": "error", "error": f"{type(e).__name__}: {e}"[:1000], "traceback": traceback.format_exc()[-4000:]})
        except Exception:  # noqa: BLE001
            pass
        if not isinstance(e, Exception):
            raise                                       # KeyboardInterrupt / SystemExit: end пишет finally
    finally:
        st["model_sec"] = round(st["model_sec"], 1)
        st["sec_per_turn"] = round(st["model_sec"] / max(1, st["turns"]), 1)
        try:
            w({"type": "end", "reason": end or "forced: interrupted", "stats": st, "reports": reports})
        finally:
            log.close()
            V.release_view(lock)
    print(json.dumps({"log": logp, "reason": end, **st}, ensure_ascii=False))
    return logp


def _loop(st, reports, w, root, prof, temp, seed, resume=None, max_turns=None, snap_name="s"):
    """Цикл сессии -> причина конца. Состояние — Run (state.py); ход — turn.py, инструменты — tools.py,
    политики контекста — context.py, финал — phase.py.
    v3b: resume — снимок (SNAPSHOT_DIR) для ветвления: история и счётчики продолжаются с него; max_turns — сколько
    ходов сделать после снимка."""
    run = R.Run(st, reports, w, root, prof, temp, seed, resume)
    if resume:
        w({"type": "resume", "from": resume.get("name"), "turn": run.turn0, "max_turns": max_turns})
    while True:
        if max_turns is not None and st["turns"] - run.turn0 >= max_turns:
            return f"fork: {max_turns} turns done"
        CX.before_turn(run, snap_name, resume)
        est = run.est()
        if est >= C.CTX - C.MAX_GEN - 1500:
            return "forced: context estimate too large to send"
        if est >= C.HARD_AT and not run.final_left:
            PH.enter_final(run, "context")
            est = run.est()
        r, dt, end = TU.ask(run, est)
        if end:
            return end
        finished, end = TU.reply(run, r, est, dt)
        end = end or PH.after_turn(run, finished)
        if end:
            return end


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--view", default=C.LAYOUT, required=C.LAYOUT is None)
    ap.add_argument("--runs", help="проваленные run через запятую (иначе --k случайных с --seed)")
    ap.add_argument("--k", type=int, default=3)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--stand", default="default", help="профиль стенда (stands/<имя>.json): модель и генерация")
    ap.add_argument("--policy", default="compact", choices=sorted(C.POLICIES))   # A2: выбрана compact (JOURNAL.md §4)
    ap.add_argument("--set", action="append", default=[], help="KEY=JSON поверх политики")
    ap.add_argument("--tag", default="t")
    ap.add_argument("--dry", action="store_true", help="только выбор трасс и промпт")
    ap.add_argument("--home", default=C.HERE, required=C.HERE is None, help="каталог сессий: logs/, views/")
    a = ap.parse_args()
    C.HERE = os.path.abspath(a.home)
    C.LAYOUT = os.path.realpath(os.path.expanduser(a.view))
    PO.apply_policy(a.policy, {k: json.loads(v) for k, v in (x.split("=", 1) for x in a.set)})
    runs = [int(x) for x in a.runs.split(",")] if a.runs else None
    if a.dry:
        print(json.dumps(V.select("rand", a.k, a.seed, runs), ensure_ascii=False))
        print(P.SYSTEM)
        print(json.dumps(P.TOOLS, indent=1))
        return
    PO.apply_stand(a.stand)
    session("rand", a.k, a.seed, C.TEMP, a.tag, runs=runs)
