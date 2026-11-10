"""Вызовы инструментов: bash, edit, finish -> (текст для модели, конец ли).
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
        return "Error: bash is no longer available; this command was not run.", False
    cmd = args.get("command")
    st["bash_calls"] += 1
    if not isinstance(cmd, str) or not cmd.strip():
        st["bad_call"] += 1
        return "Error: bash needs a 'command' string.", False
    key = " ".join(cmd.split())
    if key in run.seen:   # 6.11, автор: повтор — сказать, что нового не будет, и что делать; вывод целиком
        st["repeats"] += 1
        res["repeat"] = True
        return (f"This command was already run at tool call {run.seen[key][0]}, and no file has changed since, so it "
                f"prints the same as there (repeated below). Running it again tells you nothing new: change the "
                f"command, or go on from this output.\n{run.seen[key][1]}"), False
    ok, out, full, info, tr = F.bash_output(cmd, run.root, run.prof)
    st["denied"] += not ok
    st["truncated"] += tr
    run.seen[key] = (st["tool_calls"], out)
    res.update(ok=ok, full_chars=len(full), truncated=tr)
    return out, False


def edit_call(run, args, res):
    """Правка; применённая — сразу проверяется (pyflakes, smoke, rerun, тикет), bash на это не тратится."""
    run.st["edits_attempted"] += 1
    text, rec = ED.do_edit(args, run.root, run.st)
    rec["call"] = run.st["tool_calls"]
    rec["final"] = bool(run.final_left)
    run.items.append(rec)
    res["edit"] = {k: rec.get(k) for k in ("rel", "fail", "applied", "syntax")}
    if rec.get("applied"):
        run.seen.clear()                     # файлы изменились: повтор чтения разрешён
        text += "\n\n" + GA.edit_checks(run)
    return text, False


def do_call(run, name, raw, res):
    try:
        args = json_args(raw)
    except Exception as e:  # noqa: BLE001
        run.st["bad_call"] += 1
        res["format_fail"] = "bad_json"
        return f"Error: could not parse the arguments as JSON ({e}). Call the tool again with valid JSON arguments.", False
    if name == "bash":
        return bash_call(run, args, res)
    if name == "edit":
        return edit_call(run, args, res)
    if name == "finish":
        return GA.finish(run)
    run.st["bad_call"] += 1
    res["format_fail"] = "unknown_tool"
    names = [t["function"]["name"] for t in run.offered()]
    return f"Error: unknown tool '{name}'. Tools: {', '.join(names)}.", False
