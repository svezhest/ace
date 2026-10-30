"""Цикл сессии: session, _loop, main (CLI)."""
import argparse
import json
import os
import re
import time
import traceback

from . import cfg as C
from . import prompt as P
from . import views as V
from . import sandbox as S
from . import trace as T
from . import evidence as E
from . import model as M
from . import policy as PO


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
           "compact_req": P.COMPACT_REQ if C.COMPACT else None, "read_counter": 1, "variant": C.VARIANT, "mode": mode, "k": k, "seed": seed, "temperature": temp, "provenance": M.provenance(temp),
           "runs": tids, "selection": sel, "view": vname, "system": P.SYSTEM, "first_user": P.FIRST_USER, "limits": {
               "ctx": C.CTX, "max_gen": C.MAX_GEN, "warn_at": C.WARN_AT, "hard_at": C.HARD_AT, "clear_at": C.CLEAR_AT,
               "keep_results": C.KEEP_RESULTS, "step_budget": C.STEP_BUDGET, "remind_every": C.REMIND_EVERY,
               "final_turns": C.FINAL_TURNS, "out_chars": C.OUT_CHARS, "cmd_timeout": C.CMD_TIMEOUT,
               "max_capture": C.MAX_CAPTURE, "log_head": C.LOG_HEAD, "max_cmd": C.MAX_CMD, "max_depth": C.MAX_DEPTH,
               "api_retries": M.API_RETRIES, "clear_to": C.CLEAR_TO, "clear_at_least": C.CLEAR_AT_LEAST, "stub": C.STUB,
               "evidence_mode": C.EVIDENCE_MODE, "trace_mode": C.TRACE_MODE,
               "bash_limit": C.BASH_LIMIT, "final_fix_turns": C.FINAL_FIX_TURNS, "python": C.PYTHON,
               "runs_tool": C.RUNS_TOOL, "runs_format": C.RUNS_FORMAT, "runs_mode": C.RUNS_MODE, "say_first": C.SAY_FIRST, "checklist": C.CHECKLIST, "taxonomy": C.TAXONOMY, "diary": C.DIARY, "hypotheses": C.HYPOTHESES, "thinking": C.THINKING, "think_budget": C.THINK_BUDGET, "repeat_stop": C.REPEAT_STOP, "final_msg": C.FINAL_MSG}})
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
    """Цикл сессии -> причина конца. Каждый вызов инструмента обрабатывается под try: исключение -> модели
    'Error: ...', в лог — harness_error с трассой.
    v3b: resume — снимок (SNAPSHOT_DIR) для ветвления: история и счётчики продолжаются с него; max_turns — сколько
    ходов сделать после снимка."""
    messages = [{"role": "system", "content": P.SYSTEM}, {"role": "user", "content": P.FIRST_USER}]
    seen_cmds = {}                   # команда -> (номер вызова, индекс tool-сообщения)
    tool_msgs = []                   # индексы tool-сообщений в messages по порядку
    tool_meta = {}                   # v3b: индекс tool-сообщения -> (номер вызова, команда или имя инструмента)
    cleared = set()
    last_prompt, pending = 0, 0      # pending = оценка токенов, добавленных после последнего ответа
    warned_ctx = warned_steps = False
    since_report = 0
    final_left, final_why = 0, None
    end = None
    turn0 = 0
    if resume:
        messages = resume["messages"]
        seen_cmds = {k: tuple(v) for k, v in resume["seen_cmds"].items()}
        tool_msgs = list(resume["tool_msgs"])
        tool_meta = {int(k): tuple(v) for k, v in resume["tool_meta"].items()}
        cleared = set(resume["cleared"])
        last_prompt, pending = resume["last_prompt"], resume["pending"]
        warned_ctx, warned_steps, since_report = resume["warned_ctx"], resume["warned_steps"], resume["since_report"]
        st.update(resume["st"])
        reports.extend(resume["reports"])
        turn0 = st["turns"]
        w({"type": "resume", "from": resume.get("name"), "turn": turn0, "max_turns": max_turns})

    def snapshot():
        os.makedirs(C.SNAPSHOT_DIR, exist_ok=True)
        snap = {"name": f"{snap_name}_T{st['turns']}", "messages": messages, "seen_cmds": seen_cmds,
                "tool_msgs": tool_msgs, "tool_meta": tool_meta, "cleared": sorted(cleared),
                "last_prompt": last_prompt, "pending": pending, "warned_ctx": warned_ctx,
                "warned_steps": warned_steps, "since_report": since_report, "st": st, "reports": reports,
                "reads_acc": {r: sorted(v) for r, v in reads_acc.items()}, "scanned_acc": sorted(scanned_acc),
                "seen_acc": {r: sorted(v) for r, v in seen_acc.items()}}
        path = f"{C.SNAPSHOT_DIR}/{snap['name']}.json"
        with open(path, "w") as f:
            json.dump(snap, f, ensure_ascii=False)
        w({"type": "note", "text": f"[harness] snapshot {path}"})

    def note_user(text):
        nonlocal pending
        messages.append({"role": "user", "content": text})
        pending += M.est_tokens(text)
        w({"type": "note", "text": text})

    def stub_for(idx):
        c = messages[idx]["content"]
        call, cmd = tool_meta.get(idx, (None, ""))
        return C.STUB.format(lines=c.count("\n") + 1, chars=len(c), call=call, cmd=" ".join(str(cmd).split())[:200])

    def clear_old():
        """Старые выводы инструментов -> заглушка (как clear_tool_uses / prune в кодинг-харнессах).
        Чистим пачкой, чтобы префикс-кэш сервера сбрасывался редко. v3b: CLEAR_TO — до какой оценки чистить
        (от старых к новым), CLEAR_AT_LEAST — минимум освобождаемого, иначе история не трогается."""
        nonlocal last_prompt
        plan, freed = [], 0
        est0 = last_prompt + pending
        for idx in (tool_msgs[:-C.KEEP_RESULTS] if C.KEEP_RESULTS else tool_msgs):
            if idx in cleared:
                continue
            if C.CLEAR_TO is not None and est0 - freed <= C.CLEAR_TO:
                break
            m = messages[idx]
            if len(m["content"]) < 400:
                continue
            stub = stub_for(idx)
            plan.append((idx, stub))
            freed += M.est_tokens(m["content"]) - M.est_tokens(stub)
        if not plan or freed < C.CLEAR_AT_LEAST:
            if plan:
                w({"type": "note", "text": f"[harness] clear skipped: would free ~{freed} < {C.CLEAR_AT_LEAST}"})
            return 0
        for idx, stub in plan:
            messages[idx]["content"] = stub
            cleared.add(idx)
        last_prompt -= freed
        st["clears"] += 1
        st["cleared_results"] += len(plan)
        w({"type": "note", "text": f"[harness] cleared {len(plan)} old tool outputs, ~{freed} tokens",
           "cleared_calls": [tool_meta.get(i, (None,))[0] for i, _ in plan]})
        return len(plan)

    def compact():
        """A2 «сжатие»: модель пишет сводку; всё до хода, которому принадлежит KEEP_RESULTS-й с конца вывод,
        заменяется одним user-сообщением со сводкой и списком записанных report. Неудача -> обычная очистка."""
        nonlocal last_prompt, pending
        if len(tool_msgs) <= C.KEEP_RESULTS:
            return 0
        cut = tool_msgs[-C.KEEP_RESULTS] if C.KEEP_RESULTS else len(messages)
        while cut > 2 and messages[cut]["role"] != "assistant":
            cut -= 1
        if cut <= 2:
            return clear_old()
        t0 = time.time()
        # S4: без tools префикс шаблона другой -> кэш не берётся (233 с на 45K); те же tools.
        # S8: с tools модель ответила одним вызовом без текста -> tool_choice "none" (воркер держит tools в промпте)
        # и одна повторная просьба, если текста всё равно нет.
        req = [{"role": "user", "content": P.COMPACT_REQ}]
        summary, r, perr, tries = "", None, None, 0
        for extra in ([], [{"role": "user", "content": "Write the summary now, as plain text."}]):
            tries += 1
            resp, err = M.chat(messages + req + extra, temp, seed + 100000 + st["turns"] + tries, P.TOOLS, "none")
            r, perr = (None, err) if err else M.parse_response(resp)
            summary = ((r or {}).get("content") or "").strip()
            if summary or err:
                break
        dt = time.time() - t0
        st["model_sec"] += dt
        if not summary:
            w({"type": "note", "text": f"[harness] compaction failed ({perr or 'empty summary'}); clearing instead",
               "sec": round(dt, 1)})
            return clear_old()
        st["gen_tokens"] += r["usage"].get("completion_tokens") or 0
        rep_list = "\n".join(f"#{i + 1} ({x['kind']}): {x['observation']}" for i, x in enumerate(reports)) or "(none yet)"
        head = {"role": "user", "content": "[Earlier messages were removed from your context to save space. "
                f"Your summary of them:]\n\n{summary}\n\n[Findings recorded so far with report:]\n{rep_list}"}
        off = cut - 3
        removed_calls = [tool_meta.get(i, (None,))[0] for i in tool_msgs if i < cut]
        tool_msgs[:] = [i - off for i in tool_msgs if i >= cut]
        tm = {i - off: v for i, v in tool_meta.items() if i >= cut}
        tool_meta.clear()
        tool_meta.update(tm)
        sc = {k_: (v[0], v[1] - off) for k_, v in seen_cmds.items() if v[1] >= cut}
        seen_cmds.clear()
        seen_cmds.update(sc)
        cl = {i - off for i in cleared if i >= cut}
        cleared.clear()
        cleared.update(cl)
        messages[:] = messages[:2] + [head] + messages[cut:]
        last_prompt, pending = M.est_tokens(json.dumps(messages, ensure_ascii=False)), 0
        st["compactions"] += 1
        w({"type": "compact", "turn": st["turns"], "sec": round(dt, 1), "usage": r["usage"],
           "finish_reason": r["finish_reason"], "summary": summary, "summary_had_calls": bool(r["calls"]),
           "removed_calls": removed_calls, "removed_msgs": cut - 2, "est_after": last_prompt, "tries": tries,
           "reports_listed": len(reports)})
        return len(removed_calls)

    def enter_final(why):
        nonlocal final_left, final_why
        final_left, final_why = C.FINAL_TURNS, why
        if C.FINAL_MSG is not None:                       # 29.10: одно сообщение для всех причин
            note_user(C.FINAL_MSG)
            return
        head = (f"You have used all {C.STEP_BUDGET} tool calls." if why == "step budget" else
                f"You have used all {C.BASH_LIMIT} bash calls." if why == "bash limit" else
                f"The context is almost full (about {last_prompt + pending} of {C.CTX} tokens).")
        note_user(head + " bash is no longer available. Record each finding you can support with report now "
                  "(several report calls in one reply are fine), then call finish. Example: " + P.REPORT_EXAMPLE)

    hyps = []                        # 29.10 (R1): реестр гипотез
    rejected_now = [0]               # A1: отклонённых report в текущем ответе
    accepted_now = [0]               # A1: принятых report в текущем ответе
    pend = [False]                   # A1: в финале есть отклонённый report, после которого не было хода с принятым без отказов
    fix_left = [C.FINAL_FIX_TURNS]     # A1: сколько ходов финала ещё можно не расходовать из-за отклонённого report
    repeat_run = [0]                 # 29.10 (REPEAT_STOP): повторов подряд (сбрасывает любой вызов, кроме повтора)
    loop_hit = [False]               # 29.10: повторов подряд стало REPEAT_STOP -> финал в конце хода

    reads_acc = {r: set(v) for r, v in (resume or {}).get("reads_acc", {}).items()}
    scanned_acc = set((resume or {}).get("scanned_acc", []))
    seen_acc = {r: set(v) for r, v in (resume or {}).get("seen_acc", {}).items()}

    def note_reads(cmd, info, res):
        """Учёт открытых файлов трасс (trace_reads) -> res['reads'] и счётчики st; модели не показывается."""
        try:
            rd = T.trace_reads(cmd, root, info.get("parsed"))
        except Exception:  # noqa: BLE001
            res["reads_error"] = traceback.format_exc()[-1000:]
            return
        if rd["read"] or rd["scanned"] or rd["unresolved"]:
            res["reads"] = rd
        for r, fs in rd["read"].items():
            reads_acc.setdefault(r, set()).update(fs)
        scanned_acc.update(rd["scanned"])
        st["read_unresolved_calls"] = st.get("read_unresolved_calls", 0) + bool(rd["unresolved"])
        tr_ = sorted(r for r, fs in reads_acc.items() if T._is_trace_read(fs))
        st["traces_read"] = tr_
        st["n_traces_read"] = len(tr_)
        st["runs_opened"] = sorted(reads_acc)
        st["traces_scanned_only"] = sorted(scanned_acc - set(reads_acc))
        st["step_files_read"] = sum(sum(bool(T.STEP_FILE_RE.match(f)) for f in fs) for fs in reads_acc.values())
        st["traces_read_exact"] = sorted(r for r, fs in reads_acc.items() if T._is_trace_read([f for f in fs if f[:1] != "?"]))

    def do_call(name_, raw, res):
        """Один вызов инструмента -> (текст для модели, finish ли)."""
        nonlocal since_report
        try:
            args = json.loads(raw) if raw else {}
            if not isinstance(args, dict):
                raise ValueError("arguments must be a JSON object")
        except Exception as e:  # noqa: BLE001
            st["bad_call"] += 1
            res["format_fail"] = "bad_json"
            return f"Error: could not parse the arguments as JSON ({e}). Call the tool again with valid JSON arguments.", False
        if name_ == "runs" and C.RUNS_TOOL and C.RUNS_MODE in ("tool", "both"):
            a = args.get("args", "")
            a = a if isinstance(a, str) else " ".join(map(str, a)) if isinstance(a, list) else ""
            a = a.strip()
            if a.startswith("runs "):
                a = a[5:]
            name_, args = "bash", {"command": ("runs " + a).strip(), "_via_runs_tool": True}
            res["via_runs_tool"] = True
        if name_ == "bash" and final_left:
            st["bad_call"] += 1
            res["format_fail"] = "bash_in_final"
            return "Error: bash is no longer available. Record your findings with report, then call finish.", False
        if name_ == "bash" and C.BASH_LIMIT and st["bash_calls"] >= C.BASH_LIMIT:
            st["bash_over_limit"] += 1
            res["format_fail"] = "bash_over_limit"
            return (f"Error: all {C.BASH_LIMIT} bash calls are used; this command was not run. Record your findings "
                    "with report, then call finish."), False
        if name_ == "bash":
            st["bash_calls"] += 1
            cmd = args.get("command")
            if not isinstance(cmd, str) or not cmd.strip():
                st["bad_call"] += 1
                res["format_fail"] = "missing_arg"
                return "Error: bash needs a 'command' string.", False
            key = " ".join(cmd.split())
            prev = seen_cmds.get(key)
            if prev and prev[1] not in cleared:
                st["repeats"] += 1
                res["repeat"] = True
                if C.REPEAT_STOP:                         # 29.10: не исполняется; REPEAT_STOP подряд -> финал
                    repeat_run[0] += 1
                    res["repeat_run"] = repeat_run[0]
                    st["repeat_run_max"] = max(st["repeat_run_max"], repeat_run[0])
                    if repeat_run[0] >= C.REPEAT_STOP:
                        loop_hit[0] = True
                    return C.REPEAT_MSG, False
                old = messages[prev[1]]["content"] if prev[1] < len(messages) else ""
                head = old if len(old) <= 600 else old[:600] + f"\n[... {len(old)} characters in all]"
                return (f"This is the same command as tool call {prev[0]}, and the files have not changed, so the "
                        f"result is the same:\n{head}\n\nTo learn something new, run a different command (another "
                        "file, another range with sed -n, another pattern), or record what you have found."), False
            st["bash"] += 1
            seen_cmds[key] = (st["tool_calls"], len(messages))
            ok, out, full, info, tr = S.bash_output(cmd, root, prof)
            if not ok:
                st["denied"] += 1
            else:
                note_reads(cmd, info, res)
                seen = T.seen_runs(out, root)
                if seen:
                    res["seen"] = sorted(seen, key=int)
                    for r, cs in seen.items():
                        seen_acc.setdefault(r, set()).update(cs)
                    st["traces_seen"] = T.seen_share(seen_acc, root)
            st["truncated"] += tr
            # v3: в лог — начало вывода и длина (вывод может быть до MAX_CAPTURE байт)
            res.update(ok=ok, full_chars=len(full), truncated=tr, capped=info["capped"],
                       timed_out=info["timed_out"], output_head=full[:C.LOG_HEAD])
            return out, False
        if name_ == "report":
            kind = args.get("kind")
            obs = args.get("observation")
            ev = args.get("evidence")
            if isinstance(ev, str):
                ev = ([ev.strip()] if ev.strip() else []) if C.EVIDENCE_MODE == "free" else \
                    [x.strip() for x in re.split(r"[,\n]", ev) if x.strip()]   # free: цитату по запятым не резать
            errs = []
            if kind not in ("problem", "pattern", "meta"):
                errs.append("kind must be one of problem, pattern, meta")
            if not isinstance(obs, str) or not obs.strip():
                errs.append("observation must be a non-empty string")
            elif "\x00" in obs:
                errs.append("observation contains a NUL byte (\\x00)")
            ev_errs, ev_norm = (E.check_evidence_free if C.EVIDENCE_MODE == "free" else E.check_evidence)(ev, root)
            errs += ev_errs
            if errs:
                st["reports_rejected"] += 1
                res["rejected"] = errs
                rejected_now[0] += 1
                if final_left:
                    st["final_rejected"] += 1
                    pend[0] = True
                hint = ("Each evidence item is free-form text: a short quote with the path of its file, 'path:line', "
                        "'path:start-end' or a path; a path in it must exist in the directory. "
                        if C.EVIDENCE_MODE == "free" else
                        "Each evidence item is 'path:line' or 'path:start-end' (line numbers as grep -n or "
                        "sed -n show them); a file of up to 80 lines may be given by its path alone. ")
                return ("Error: report not recorded.\n- " + "\n- ".join(errs) + "\n" + hint +
                        "Fix it and call report again, e.g. " + P.REPORT_EXAMPLE), False
            st["reports_ok"] += 1
            accepted_now[0] += 1
            st["first_report_call"] = st["first_report_call"] or st["tool_calls"]
            reports.append({"kind": kind, "observation": obs, "evidence": ev_norm, "evidence_raw": ev,
                            "step": st["tool_calls"], "final": bool(final_left)})
            res["recorded"] = len(reports)
            since_report = -1
            return f"Recorded finding #{len(reports)}.", False
        if name_ == "note" and C.NOTES and not final_left:
            txt = args.get("text")
            if not isinstance(txt, str) or not txt.strip():
                st["bad_call"] += 1
                res["format_fail"] = "missing_arg"
                return "Error: note needs a 'text' string.", False
            st["notes"] += 1
            return "Noted.", False
        if name_ == "hypothesis" and C.HYPOTHESES:
            cl = args.get("claim")
            if not isinstance(cl, str) or not cl.strip():
                st["bad_call"] += 1
                res["format_fail"] = "missing_arg"
                return "Error: hypothesis needs a 'claim' string.", False
            hyps.append({"id": f"H{len(hyps) + 1}", "claim": cl.strip(), "confirms_if": str(args.get("confirms_if", "")),
                         "refutes_if": str(args.get("refutes_if", "")), "result": "open"})
            st["hypotheses"] = len(hyps)
            return f"{hyps[-1]['id']} recorded.", False
        if name_ == "verdict" and C.HYPOTHESES:
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
        if name_ == "finish":
            if final_left and pend[0] and fix_left[0] > 0:
                st["finish_deferred"] += 1
                res["deferred"] = True
                return ("Not finished yet: a report call was not recorded (the reason is in its result). Fix it "
                        "and call report again, then call finish."), False
            return "Finished.", True
        st["bad_call"] += 1
        res["format_fail"] = "unknown_tool"
        return (f"Error: unknown tool '{name_}'. Tools: " +
                ("report, finish." if final_left else ", ".join(x["function"]["name"] for x in P.TOOLS) + ".")), False

    while end is None:
        if max_turns is not None and st["turns"] - turn0 >= max_turns:
            end = f"fork: {max_turns} turns done"
            break
        if C.CLEAR_AT is not None and last_prompt + pending >= C.CLEAR_AT and not final_left:
            if C.SNAPSHOT_DIR and not resume:
                snapshot()
            compact() if C.COMPACT else clear_old()
        est = last_prompt + pending
        if est >= C.CTX - C.MAX_GEN - 1500:
            end = "forced: context estimate too large to send"
            break
        if est >= C.HARD_AT and not final_left:
            enter_final("context")
            est = last_prompt + pending
        t0 = time.time()
        r = perr = None
        for attempt in range(M.API_RETRIES + 1):
            resp, err = M.chat(messages, temp, seed + st["turns"], P.FINAL_TOOLS if final_left else P.TOOLS)
            if err:
                break
            r, perr = M.parse_response(resp)
            if r:
                break
            w({"type": "api_error", "turn": st["turns"] + 1, "attempt": attempt + 1, "error": perr,
               "response": json.dumps(resp, ensure_ascii=False)[:2000]})
            if attempt < M.API_RETRIES:
                st["api_retries"] += 1
                time.sleep(M.API_RETRY_SEC)
        dt = time.time() - t0
        st["model_sec"] += dt
        st["turns"] += 1
        st["final_turns"] += bool(final_left)
        if err:
            w({"type": "turn", "i": st["turns"], "sec": round(dt, 1), "error": err, "est_prompt": est})
            end = f"forced: model call failed: {err[:200]}"
            break
        if not r:
            w({"type": "turn", "i": st["turns"], "sec": round(dt, 1), "error": f"bad response: {perr}",
               "est_prompt": est})
            end = f"forced: bad API response after {M.API_RETRIES + 1} attempts: {perr}"
            break
        u = r["usage"]
        last_prompt = (u.get("prompt_tokens") or est) + (u.get("completion_tokens") or 0)
        pending = 0
        st["gen_tokens"] += u.get("completion_tokens") or 0
        st["max_prompt"] = max(st["max_prompt"], u.get("prompt_tokens") or 0)
        if r["finish_reason"] == "length":
            st["length_stops"] += 1
        calls = r["calls"]
        rec = {"type": "turn", "i": st["turns"], "sec": round(dt, 1), "usage": u, "est_prompt": est,
               "final": bool(final_left), "finish_reason": r["finish_reason"], "content": r["content"], "reasoning": r.get("reasoning"),
               "tool_calls": [{"name": c["function"]["name"], "arguments": c["function"]["arguments"]} for c in calls],
               "results": []}
        if r["bad"]:
            rec["malformed_calls"] = r["bad"]
            st["bad_call"] += r["bad"]
        amsg = {"role": "assistant", "content": r["content"] or ""}
        if calls:
            amsg["tool_calls"] = [{"id": c["id"] or f"call_{st['turns']}_{j}", "type": "function",
                                   "function": {"name": c["function"]["name"], "arguments": c["function"]["arguments"]}}
                                  for j, c in enumerate(calls)]
        messages.append(amsg)
        finished = False
        rejected_now[0] = accepted_now[0] = 0
        if not calls:
            st["no_call"] += 1
            txt = r["content"] or ""
            kind = "malformed" if (r["bad"] or "<tool_call>" in txt or "<function=" in txt) else "none"
            note = ("Your reply contained a tool call the system could not parse. Call a tool again using the "
                    "tool-calling format." if kind == "malformed" else
                    "Your reply contained no tool call. Continue with bash, record findings with report, or call finish."
                    if not final_left else "Your reply contained no tool call. Call report for each supported finding, then finish.")
            rec["format_fail"] = kind
            note_user(note)
            w(rec)
            if st["no_call"] >= 6 and not final_left:
                end = "forced: too many replies without a tool call"
        for c in amsg.get("tool_calls", []):
            name_, raw = c["function"]["name"], c["function"]["arguments"]
            st["tool_calls"] += 1
            res = {"name": name_, "arguments": raw}
            try:
                if (C.SAY_FIRST and not final_left and name_ in ("bash", "runs") and st.get("bash_calls", 0) > 0
                        and len((r["content"] or "").strip()) < C.SAY_FIRST):
                    st["say_rejected"] = st.get("say_rejected", 0) + 1
                    res["say_rejected"] = True
                    out, finished = P.SAY_MSG, False
                else:
                    out, finished = do_call(name_, raw, res)
            except Exception as e:  # noqa: BLE001  v3c: ответ модели не роняет харнесс
                st["harness_errors"] += 1
                res["harness_error"] = traceback.format_exc()[-2000:]
                out, finished = f"Error: {type(e).__name__}: {str(e)[:300]}", False
            since_report += 1
            if C.REPEAT_STOP and not res.get("repeat"):
                repeat_run[0] = 0
            # приписки цикла: контекст, шаги, давно не было report
            left = C.STEP_BUDGET - st["tool_calls"]
            est_now = last_prompt + pending + M.est_tokens(out)
            if not finished and not final_left:
                if C.WARN_AT is not None and est_now >= C.WARN_AT and not warned_ctx:
                    warned_ctx = True
                    out += (f"\n\n[note: about {est_now} of {C.CTX} context tokens used. Start wrapping up: report the "
                            "findings you can support, then call finish.]")
                if left <= C.STEP_BUDGET - C.STEP_WARN and not warned_steps:
                    warned_steps = True
                    out += f"\n\n[note: {left} tool calls left. Report what you have found, then call finish.]"
                elif C.REMIND_EVERY and since_report and since_report % C.REMIND_EVERY == 0:
                    st["reminders"] += 1
                    out += (f"\n\n[note: {since_report} tool calls since your last recorded finding; {left} of "
                            f"{C.STEP_BUDGET} calls left. If something you checked is supported by lines you have read, "
                            "record it with report now.]")
            if C.HYPOTHESES and hyps and name_ in ("bash", "runs") and not final_left:
                out += "\n\n[hypotheses: " + "; ".join(
                    f"{x['id']} {x['result']}: {x['claim'][:110]}" for x in hyps[-8:]) + "]"
            res["shown"] = out if res.get("output_head") != out else "(= output_head)"
            rec["results"].append(res)
            tool_meta[len(messages)] = (st["tool_calls"], _cmd_of(name_, raw))
            tool_msgs.append(len(messages))
            messages.append({"role": "tool", "tool_call_id": c["id"], "content": out})
            pending += M.est_tokens(out) + 10
            if finished:
                break
        if calls:
            w(rec)
        if end:
            break
        if finished:
            end = "finish"
        elif final_left:
            if accepted_now[0] and not rejected_now[0]:
                pend[0] = False
            if pend[0] and fix_left[0] > 0:
                fix_left[0] -= 1                        # A1: отклонённый report ещё не исправлен — финал не сокращается
                st["final_fix_used"] += 1
                w({"type": "note", "text": f"[harness] final turn not counted: a rejected report is not fixed yet "
                   f"({rejected_now[0]} rejected this turn); {fix_left[0]} such turns left"})
            else:
                final_left -= 1
            if not final_left:
                end = f"forced: {final_why} (final turns used)"
        elif loop_hit[0]:
            loop_hit[0] = False
            st["loop_final"] += 1
            enter_final("loop")
        elif st["tool_calls"] >= C.STEP_BUDGET:
            enter_final("step budget")
        elif C.BASH_LIMIT and st["bash_calls"] >= C.BASH_LIMIT:
            enter_final("bash limit")
    return end


def _cmd_of(name_, raw):
    if name_ != "bash":
        return name_
    try:
        return json.loads(raw).get("command", "")
    except Exception:  # noqa: BLE001
        return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--view", default=C.LAYOUT)
    ap.add_argument("--runs", help="проваленные run через запятую (иначе --k случайных с --seed)")
    ap.add_argument("--k", type=int, default=3)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--temp", type=float, default=0.6)
    ap.add_argument("--policy", default="compact", choices=sorted(C.POLICIES))   # A2: выбрана compact (JOURNAL.md §4)
    ap.add_argument("--set", action="append", default=[], help="KEY=JSON поверх политики")
    ap.add_argument("--tag", default="t")
    ap.add_argument("--dry", action="store_true", help="только выбор трасс и промпт")
    a = ap.parse_args()
    C.LAYOUT = os.path.realpath(os.path.expanduser(a.view))
    PO.apply_policy(a.policy, {k: json.loads(v) for k, v in (x.split("=", 1) for x in a.set)})
    runs = [int(x) for x in a.runs.split(",")] if a.runs else None
    if a.dry:
        print(json.dumps(V.select("rand", a.k, a.seed, runs), ensure_ascii=False))
        print(P.SYSTEM)
        print(json.dumps(P.TOOLS, indent=1))
        return
    session("rand", a.k, a.seed, a.temp, a.tag, runs=runs)
