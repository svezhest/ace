"""Вызовы инструментов: bash, edit (редактор), propose (шаг вариантов), finish -> (текст для модели, конец ли).
res — запись вызова для лога (поля дописываются сюда)."""
import json

from .cfg import F
from . import cfg as C
from . import edit as ED
from . import gate as GA


def json_args(raw):
    args = json.loads(raw) if raw else {}
    if not isinstance(args, dict):
        raise ValueError("arguments must be a JSON object")
    return args


def bash_call(run, args, res):
    st = run.st
    if run.final_left or st["bash_calls"] >= C.BASH_LIMIT:
        st["bad_call"] += 1
        res["format_fail"] = "bash_unavailable"
        return f"Error: bash is no longer available; this command was not run. Use {run.act}, then call finish.", False
    cmd = args.get("command")
    st["bash_calls"] += 1
    if not isinstance(cmd, str) or not cmd.strip():
        st["bad_call"] += 1
        return "Error: bash needs a 'command' string.", False
    key = " ".join(cmd.split())
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
    text, rec = ED.do_edit(args, run.root, run.st)
    rec["call"] = run.st["tool_calls"]
    rec["final"] = bool(run.final_left)
    run.items.append(rec)
    res["edit"] = {k: rec.get(k) for k in ("rel", "fail", "applied", "syntax")}
    if rec.get("applied"):
        run.seen.clear()                     # файлы изменились: повтор чтения разрешён
    return text, False


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
    if name == "finish":
        return GA.finish(run)
    run.st["bad_call"] += 1
    res["format_fail"] = "unknown_tool"
    names = [t["function"]["name"] for t in run.offered()]
    return f"Error: unknown tool '{name}'. Tools: {', '.join(names)}.", False
