"""Вызовы инструментов: bash, report, note, hypothesis, verdict, finish -> (текст для модели, finish ли).
res — запись вызова для лога (поля дописываются сюда)."""
import json
import re
import traceback

from . import cfg as C
from . import prompt as P
from . import sandbox as S
from . import trace as T
from . import evidence as E
from . import nudge as NG


def call(run, name_, raw, res, said):
    """Вызов под try: исключение -> модели 'Error: ...', в лог — harness_error с трассой.
    said — текст ответа модели (SAY_FIRST: без него bash/runs не исполняются)."""
    st = run.st
    try:
        if (C.SAY_FIRST and not run.final_left and name_ in ("bash", "runs") and st.get("bash_calls", 0) > 0
                and len((said or "").strip()) < C.SAY_FIRST):
            st["say_rejected"] = st.get("say_rejected", 0) + 1
            res["say_rejected"] = True
            st["bash_calls"] += 1                 # 31.10: отказ тратит вызов, иначе петля без конца (r4app_say)
            return P.SAY_MSG, False
        refused = NG.gate(run, name_, res)
        if refused:
            return refused, False
        return do_call(run, name_, raw, res)
    except Exception as e:  # noqa: BLE001  v3c: ответ модели не роняет харнесс
        st["harness_errors"] += 1
        res["harness_error"] = traceback.format_exc()[-2000:]
        return f"Error: {type(e).__name__}: {str(e)[:300]}", False


def do_call(run, name_, raw, res):
    """Один вызов инструмента -> (текст для модели, finish ли)."""
    try:
        args = json.loads(raw) if raw else {}
        if not isinstance(args, dict):
            raise ValueError("arguments must be a JSON object")
    except Exception as e:  # noqa: BLE001
        run.st["bad_call"] += 1
        res["format_fail"] = "bad_json"
        return f"Error: could not parse the arguments as JSON ({e}). Call the tool again with valid JSON arguments.", False
    if name_ == "runs" and C.RUNS_TOOL and C.RUNS_MODE in ("tool", "both"):
        name_, args = "bash", _runs_as_bash(args, res)
    if name_ == "bash":
        return _bash(run, args, res)
    if name_ == "report":
        return _report(run, args, res)
    if name_ == "note" and C.NOTES and not run.final_left:
        return _note(run, args, res)
    if name_ == "hypothesis" and C.HYPOTHESES:
        return _hypothesis(run, args, res)
    if name_ == "verdict" and C.HYPOTHESES:
        return _verdict(run, args, res)
    if name_ == "finish":
        return _finish(run, res)
    run.st["bad_call"] += 1
    res["format_fail"] = "unknown_tool"
    return (f"Error: unknown tool '{name_}'. Tools: " +
            ("report, finish." if run.final_left else ", ".join(x["function"]["name"] for x in P.TOOLS) + ".")), False


def _missing(run, res, text):
    run.st["bad_call"] += 1
    res["format_fail"] = "missing_arg"
    return text, False


# ---------------------------------------------------------------- bash

def _runs_as_bash(args, res):
    """Инструмент runs(args) -> аргументы bash с командой runs ..."""
    a = args.get("args", "")
    a = a if isinstance(a, str) else " ".join(map(str, a)) if isinstance(a, list) else ""
    a = a.strip()
    if a.startswith("runs "):
        a = a[5:]
    res["via_runs_tool"] = True
    return {"command": ("runs " + a).strip(), "_via_runs_tool": True}


def _bash(run, args, res):
    st = run.st
    if run.final_left:
        st["bad_call"] += 1
        res["format_fail"] = "bash_in_final"
        return "Error: bash is no longer available. Record your findings with report, then call finish.", False
    if C.BASH_LIMIT and st["bash_calls"] >= C.BASH_LIMIT:
        st["bash_over_limit"] += 1
        res["format_fail"] = "bash_over_limit"
        return (f"Error: all {C.BASH_LIMIT} bash calls are used; this command was not run. Record your findings "
                "with report, then call finish."), False
    st["bash_calls"] += 1
    cmd = args.get("command")
    if not isinstance(cmd, str) or not cmd.strip():
        return _missing(run, res, "Error: bash needs a 'command' string.")
    key = " ".join(cmd.split())
    prev = run.seen_cmds.get(key)
    if prev and prev[1] not in run.cleared:
        return _repeat(run, prev, res), False
    st["bash"] += 1
    run.seen_cmds[key] = (st["tool_calls"], len(run.messages))
    ok, out, full, info, tr = S.bash_output(cmd, run.root, run.prof)
    if not ok:
        st["denied"] += 1
    else:
        note_reads(run, cmd, info, res)
        note_seen(run, out, res)
    st["truncated"] += tr
    # v3: в лог — начало вывода и длина (вывод может быть до MAX_CAPTURE байт)
    res.update(ok=ok, full_chars=len(full), truncated=tr, capped=info["capped"],
               timed_out=info["timed_out"], output_head=full[:C.LOG_HEAD])
    return out, False


def _repeat(run, prev, res):
    """Команда уже была и её вывод в контексте -> не исполняется."""
    st = run.st
    st["repeats"] += 1
    res["repeat"] = True
    if C.REPEAT_STOP:                         # 29.10: не исполняется; REPEAT_STOP подряд -> финал
        run.repeat_run += 1
        res["repeat_run"] = run.repeat_run
        st["repeat_run_max"] = max(st["repeat_run_max"], run.repeat_run)
        if run.repeat_run >= C.REPEAT_STOP:
            run.loop_hit = True
        return C.REPEAT_MSG
    old = run.messages[prev[1]]["content"] if prev[1] < len(run.messages) else ""
    head = old if len(old) <= 600 else old[:600] + f"\n[... {len(old)} characters in all]"
    return (f"This is the same command as tool call {prev[0]}, and the files have not changed, so the "
            f"result is the same:\n{head}\n\nTo learn something new, run a different command (another "
            "file, another range with sed -n, another pattern), or record what you have found.")


def note_reads(run, cmd, info, res):
    """Учёт открытых файлов трасс (trace_reads) -> res['reads'] и счётчики st; модели не показывается."""
    st, reads_acc = run.st, run.reads_acc
    try:
        rd = T.trace_reads(cmd, run.root, info.get("parsed"))
    except Exception:  # noqa: BLE001
        res["reads_error"] = traceback.format_exc()[-1000:]
        return
    if rd["read"] or rd["scanned"] or rd["unresolved"]:
        res["reads"] = rd
    for r, fs in rd["read"].items():
        reads_acc.setdefault(r, set()).update(fs)
    run.scanned_acc.update(rd["scanned"])
    st["read_unresolved_calls"] = st.get("read_unresolved_calls", 0) + bool(rd["unresolved"])
    tr_ = sorted(r for r, fs in reads_acc.items() if T._is_trace_read(fs))
    st["traces_read"] = tr_
    st["n_traces_read"] = len(tr_)
    st["runs_opened"] = sorted(reads_acc)
    st["traces_scanned_only"] = sorted(run.scanned_acc - set(reads_acc))
    st["step_files_read"] = sum(sum(bool(T.STEP_FILE_RE.match(f)) for f in fs) for fs in reads_acc.values())
    st["traces_read_exact"] = sorted(r for r, fs in reads_acc.items() if T._is_trace_read([f for f in fs if f[:1] != "?"]))


def note_seen(run, out, res):
    """Шаги run, показанные в выводе (seen_runs) -> res['seen'] и st['traces_seen']."""
    seen = T.seen_runs(out, run.root)
    if seen:
        res["seen"] = sorted(seen, key=int)
        for r, cs in seen.items():
            run.seen_acc.setdefault(r, set()).update(cs)
        run.st["traces_seen"] = T.seen_share(run.seen_acc, run.root)


# ---------------------------------------------------------------- report

def _report_errors(kind, obs, ev, root):
    """-> (ошибки, нормализованные evidence)."""
    errs = []
    if kind not in ("problem", "pattern", "meta"):
        errs.append("kind must be one of problem, pattern, meta")
    if not isinstance(obs, str) or not obs.strip():
        errs.append("observation must be a non-empty string")
    elif "\x00" in obs:
        errs.append("observation contains a NUL byte (\\x00)")
    ev_errs, ev_norm = (E.check_evidence_free if C.EVIDENCE_MODE == "free" else E.check_evidence)(ev, root)
    return errs + ev_errs, ev_norm


def _report(run, args, res):
    st = run.st
    kind = args.get("kind")
    obs = args.get("observation")
    ev = args.get("evidence")
    if isinstance(ev, str):
        ev = ([ev.strip()] if ev.strip() else []) if C.EVIDENCE_MODE == "free" else \
            [x.strip() for x in re.split(r"[,\n]", ev) if x.strip()]   # free: цитату по запятым не резать
    errs, ev_norm = _report_errors(kind, obs, ev, run.root)
    if errs:
        st["reports_rejected"] += 1
        res["rejected"] = errs
        run.rejected_now += 1
        if run.final_left:
            st["final_rejected"] += 1
            run.pend = True
        hint = ("Each evidence item is free-form text: a short quote with the path of its file, 'path:line', "
                "'path:start-end' or a path; a path in it must exist in the directory. "
                if C.EVIDENCE_MODE == "free" else
                "Each evidence item is 'path:line' or 'path:start-end' (line numbers as grep -n or "
                "sed -n show them); a file of up to 80 lines may be given by its path alone. ")
        return ("Error: report not recorded.\n- " + "\n- ".join(errs) + "\n" + hint +
                "Fix it and call report again, e.g. " + P.REPORT_EXAMPLE), False
    st["reports_ok"] += 1
    run.accepted_now += 1
    st["first_report_call"] = st["first_report_call"] or st["tool_calls"]
    run.reports.append({"kind": kind, "observation": obs, "evidence": ev_norm, "evidence_raw": ev,
                        "step": st["tool_calls"], "final": bool(run.final_left)})
    res["recorded"] = len(run.reports)
    run.since_report = -1
    return f"Recorded finding #{len(run.reports)}.", False


# ---------------------------------------------------------------- note, hypothesis, verdict, finish

def _note(run, args, res):
    txt = args.get("text")
    if not isinstance(txt, str) or not txt.strip():
        return _missing(run, res, "Error: note needs a 'text' string.")
    run.st["notes"] += 1
    return "Noted.", False


def _hypothesis(run, args, res):
    hyps = run.hyps
    cl = args.get("claim")
    if not isinstance(cl, str) or not cl.strip():
        return _missing(run, res, "Error: hypothesis needs a 'claim' string.")
    hyps.append({"id": f"H{len(hyps) + 1}", "claim": cl.strip(), "confirms_if": str(args.get("confirms_if", "")),
                 "refutes_if": str(args.get("refutes_if", "")), "result": "open"})
    run.st["hypotheses"] = len(hyps)
    return f"{hyps[-1]['id']} recorded.", False


def _verdict(run, args, res):
    st, hyps = run.st, run.hyps
    hid = str(args.get("id", "")).strip().upper()
    rr = args.get("result")
    h = next((x for x in hyps if x["id"] == hid), None)
    if h is None or rr not in ("held", "refuted", "unclear"):
        st["bad_call"] += 1
        res["format_fail"] = "bad_verdict"
        return ("Error: verdict needs an existing id (" + (", ".join(x["id"] for x in hyps) or "none yet")
                + ") and result held, refuted or unclear."), False
    h["result"], h["why"] = rr, str(args.get("why", ""))
    st["verdicts_" + rr] = st.get("verdicts_" + rr, 0) + 1
    return f"{hid}: {rr}.", False


def _finish(run, res):
    if run.final_left and run.pend and run.fix_left > 0:
        run.st["finish_deferred"] += 1
        res["deferred"] = True
        return ("Not finished yet: a report call was not recorded (the reason is in its result). Fix it "
                "and call report again, then call finish."), False
    return "Finished.", True
