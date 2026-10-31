"""Вызов инструмента: finish, bash (повтор не исполняется), инструмент роли (handle), неизвестный."""
import json

from . import cfg as C
from . import sandbox as SB


def parse_args(raw):
    """-> dict (не объект JSON -> {}) или None, если это не JSON."""
    try:
        args = json.loads(raw) if raw else {}
        return args if isinstance(args, dict) else {}
    except ValueError:
        return None


def call(run, name, raw):
    """-> (текст для модели, принят ли вызов, finish ли)."""
    args = parse_args(raw)
    if args is None:
        return "Error: could not parse the arguments as JSON. Call the tool again with valid JSON arguments.", False, False
    if name == "finish":
        return "Finished.", True, True
    if name == "bash" and not run.final_left:
        out, ok = bash(run, args)
        return out, ok, False
    if name in [t["function"]["name"] for t in run.role_tools]:
        out, ok = role(run, name, args)
        return out, ok, False
    names = ", ".join(t["function"]["name"] for t in run.offered())
    return f"Error: unknown tool '{name}' here. Tools: {names}.", False, False


def bash(run, args):
    cmd = str(args.get("command", ""))
    key = " ".join(cmd.split())
    run.bash_calls += 1                  # лимит считает все вызовы bash, и повторы тоже
    if key in run.seen:
        run.repeats += 1
        return C.REPEAT_MSG, False
    run.seen.add(key)
    return SB.run_bash(cmd, run.root, run.prof), True


def role(run, name, args):
    try:
        out, ok = run.handle(name, args)
    except Exception as e:  # noqa: BLE001  ответ модели не роняет сессию
        out, ok = f"Error: {type(e).__name__}: {str(e)[:300]}", False
    if ok and name == "edit":
        run.seen.clear()                 # файлы изменились: прежние команды снова осмысленны
    run.rejected |= not ok
    return out, ok
