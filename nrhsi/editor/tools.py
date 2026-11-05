"""Вызовы инструментов: bash, edit (редактор), propose (шаг вариантов), finish -> (текст для модели, конец ли).
res — запись вызова для лога (поля дописываются сюда)."""
import json
import re

from .cfg import F
from . import cfg as C
from . import edit as ED
from . import gate as GA
from . import work as WK


def json_args(raw):
    args = json.loads(raw) if raw else {}
    if not isinstance(args, dict):
        raise ValueError("arguments must be a JSON object")
    return args


def bash_call(run, args, res):
    st = run.st
    if run.final_left or st["bash_calls"] >= run.bash_limit:
        st["bad_call"] += 1
        res["format_fail"] = "bash_unavailable"
        return f"Error: bash is no longer available; this command was not run. Use {run.act}, then call finish.", False
    cmd = args.get("command")
    st["bash_calls"] += 1
    if not isinstance(cmd, str) or not cmd.strip():
        st["bad_call"] += 1
        return "Error: bash needs a 'command' string.", False
    key = " ".join(cmd.split())
    m = (re.match(r"(rerun|smoke)((?: [\w-]+)*)((?: \| (?:head|tail|grep|wc|nl|sed)\b[^;&`$<>(){}|]*)*)$", key)
         if C.HIDE_TOOLS else None)       # 5.11 --hide-tools: rerun и smoke — команды харнесса, можно с | head и т.п.
    if C.HIDE_TOOLS and not m and re.match(r"(rerun|smoke)\b", key):
        return ("Error: rerun and smoke run on their own; only | head, tail, grep, wc, nl or sed may follow "
                "them."), False
    if m and key not in run.seen:
        if m.group(1) == "smoke" and m.group(2):
            return "Error: smoke takes no arguments.", False
        ok, out, full = WK.tool_run(run, m.group(1), (m.group(2) or "") + (m.group(3) or ""))
        st["denied"] += not ok
        run.seen[key] = (st["tool_calls"], out)
        res.update(ok=ok, full_chars=len(full), truncated=len(full) > len(out))
        return out, False
    if key in run.seen:
        st["repeats"] += 1
        res["repeat"] = True
        old = run.seen[key][1]
        head = old if len(old) <= 600 else old[:600] + f"\n[... {len(old)} characters in all]"
        return (f"This is the same command as tool call {run.seen[key][0]}, and the files have not changed since, "
                f"so the result is the same:\n{head}"), False
    ok, out, full, info, tr = F.bash_output(cmd, run.root, run.prof)
    st["denied"] += not ok
    st["truncated"] += tr
    run.seen[key] = (st["tool_calls"], out)
    res.update(ok=ok, full_chars=len(full), truncated=tr)
    return out, False


def edit_call(run, args, res):
    run.st["edits_attempted"] += 1
    if C.CHECKED and run.final_left:
        run.st["edit_fail"]["unchecked"] = run.st["edit_fail"].get("unchecked", 0) + 1
        res["edit"] = {"rel": args.get("path"), "fail": "unchecked", "applied": False}
        run.items.append({"path": args.get("path"), "fail": "unchecked", "call": run.st["tool_calls"], "final": True})
        return "Error: edit not applied: no bash calls left to check it. Call finish.", False
    text, rec = ED.do_edit(args, run.root, run.st)
    rec["call"] = run.st["tool_calls"]
    rec["final"] = bool(run.final_left)
    run.items.append(rec)
    res["edit"] = {k: rec.get(k) for k in ("rel", "fail", "applied", "syntax")}
    if rec.get("applied"):
        run.seen.clear()                     # файлы изменились: повтор чтения разрешён
        if C.STAGES and not run.stage2:
            run.stage2, run.bash_limit = True, run.st["bash_calls"] + C.STAGES[1]
            text += (f"\n\nThis is your first edit, so the check part starts: you have {C.STAGES[1]} bash calls "
                     "left to check your edits.")
        if C.AUTO_CHECK:
            text += "\n\n" + GA.edit_checks(run)
    return text, False


def rerun_call(run, args, res):
    """--rerun-tool: rerun(expect_diff, run) -> ok / failed по ожиданию (none | prompt | control), затем вывод повтора."""
    ex, n = args.get("expect_diff"), args.get("run")
    if ex not in ("none", "prompt", "control"):
        run.st["bad_call"] += 1
        res["format_fail"] = "bad_args"
        return "Error: expect_diff is required: none, prompt or control.", False
    if n is not None:
        try:
            n = int(n)
        except (TypeError, ValueError):
            run.st["bad_call"] += 1
            res["format_fail"] = "bad_args"
            return "Error: run must be a run number.", False
    run.st["reruns"] = run.st.get("reruns", 0) + 1
    out, changed = GA.rerun_output(run, n)
    top = [l for l in out.splitlines() if l.strip() and not l[0].isspace() and not l.startswith("…")]
    got = ("none" if not changed else
           "prompt" if top and all("the prompt differs from the log" in l for l in top) else "control")
    res.update(expect_diff=ex, got_diff=got)
    if ex == got:
        return ("ok, no changes" if got == "none" else "ok:\n" + out), False
    return ("failed: no changes!" if got == "none" else "failed!:\n" + out), False


def check_proposal(args, n_obs):
    """-> (problem, fix, номера наблюдений, ошибки)."""
    p, fx, ob = args.get("problem"), args.get("fix"), args.get("observations")
    errs = []
    if not isinstance(p, str) or not p.strip():
        errs.append("problem must be a non-empty string")
    if not isinstance(fx, str) or not fx.strip():
        errs.append("fix must be a non-empty string")
    if isinstance(ob, (int, str)):
        ob = [ob]
    try:
        ob = [int(x) for x in (ob or [])]
    except (TypeError, ValueError):
        ob = None
    if ob is None or any(not 1 <= x <= n_obs for x in ob):
        errs.append(f"observations must be a list of observation numbers from 1 to {n_obs}")
    return p, fx, ob, errs


def propose_call(run, args, res):
    st = run.st
    p, fx, ob, errs = check_proposal(args, run.n_obs)
    if errs:
        st["proposals_rejected"] += 1
        res["rejected"] = errs
        return "Error: proposal not recorded: " + "; ".join(errs) + ".", False
    st["proposals"] += 1
    run.items.append({"problem": p.strip(), "fix": fx.strip(), "observations": ob, "call": st["tool_calls"],
                      "final": bool(run.final_left)})
    return f"Proposal {st['proposals']} recorded.", False


def do_call(run, name, raw, res):
    try:
        args = json_args(raw)
    except Exception as e:  # noqa: BLE001
        run.st["bad_call"] += 1
        res["format_fail"] = "bad_json"
        return f"Error: could not parse the arguments as JSON ({e}). Call the tool again with valid JSON arguments.", False
    if name == "bash":
        return bash_call(run, args, res)
    if name == "edit" and run.role == "editor":
        return edit_call(run, args, res)
    if name == "propose" and run.role == "proposer":
        return propose_call(run, args, res)
    if name == "rerun" and C.RERUN_TOOL:
        return rerun_call(run, args, res)
    if name == "finish":
        return GA.finish(run, args)
    run.st["bad_call"] += 1
    res["format_fail"] = "unknown_tool"
    names = [t["function"]["name"] for t in run.offered()]
    return f"Error: unknown tool '{name}'. Tools: {', '.join(names)}.", False
