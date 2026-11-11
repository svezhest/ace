"""rerun: прогнать src по записанным прогонам вида и показать, где поведение харнесса расходится с логом.

  python3 editor/rerun.py --bench alf --src <dir>/src --logs <view>/logs [--old <view>/src] [N ...]

Модель и бенчмарк не вызываются: ответы модели и сообщения задачи берутся из лога. Пока то, что харнесс
даёт модели и задаче, совпадает с записью, запись честна; на первом расхождении прогон останавливается и
печатается разница: что было в логе (-) и что теперь (+). Дальше лог уже не про этот src.
Хуки логируются обёрткой вне src: имя, что вернул, исключение. С --old те же прогоны идут и на старом src,
и показываются хуки, которые стали отвечать иначе (даже если до модели это не дошло).
"""
import argparse
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
BENCH = {"alf": ROOT / "alfworld", "app": ROOT / "appworld"}
TASK_SYSTEM = {"role": "system", "content": "<the task's own system message: not in the log>"}


def key(m):
    return json.dumps(m, sort_keys=True, ensure_ascii=False)


ADDED_CHARS = 2000       # знаков сообщения, которое харнесс теперь добавляет в разговор
WAS_CHARS = 110          # знаков того, что стояло в логе на месте расхождения (сводка)
SAME_RUNS = 3            # столько прогонов одной группы сводка называет по отдельности, остальные — одной строкой


def short(m, n=160):
    if m is None:
        return "-"
    if "tool_calls" in m and m.get("tool_calls"):
        a = m["tool_calls"][0]["function"]["arguments"]
        try:
            a = json.loads(a).get("action", a)
        except Exception:
            pass
        s = f"take_action: {a}"
        if (m.get("content") or "").strip():
            s = (m["content"].strip().splitlines() or [""])[0][:80] + " | " + s
    else:
        s = (m.get("content") or "").strip()
    s = s.replace("\n", "\\n")
    return f'{m["role"]}: {s[:n]}{"…" if len(s) > n else ""}'


def val(x, depth=0):
    """--at: значение коротко — строки до 100 символов, у длинных списков — последние 3, словари до 2 уровней."""
    if isinstance(x, dict):
        if depth > 1:
            return f"dict[{len(x)}]"
        items = [f"{k!r}: {val(v, depth + 1)}" for k, v in list(x.items())[:12]]
        return "{" + ", ".join(items) + (", ..." if len(x) > 12 else "") + "}"
    if isinstance(x, (list, tuple)):
        if depth > 2:
            return f"{type(x).__name__}[{len(x)}]"
        xs = [val(v, depth + 1) for v in x[-3:]]
        body = ", ".join(([f"... {len(x) - 3} more"] if len(x) > 3 else []) + xs)
        return ("[" + body + "]") if isinstance(x, list) else ("(" + body + ("," if len(x) == 1 else "") + ")")
    if isinstance(x, (str, int, float, bool, type(None))):
        r = repr(x)
        return r if len(r) <= 100 else r[:100] + "…"
    if hasattr(x, "__dataclass_fields__") and not isinstance(x, type):
        if depth > 2:
            return f"{type(x).__name__}(...)"
        return f"{type(x).__name__}(" + ", ".join(f"{k}={val(getattr(x, k), depth + 1)}" for k in x.__dataclass_fields__) + ")"
    if isinstance(x, type) or callable(x):
        return getattr(x, "__name__", f"<{type(x).__name__}>")
    return f"<{type(x).__name__}>"


# ---------------------------------------------------------------- worker: один src в своём процессе
class Diverged(Exception):
    pass


def load_log(path):
    ev = [json.loads(l) for l in open(path)]
    conv, line_of = [], []          # сообщения в порядке разговора и номер строки лога у каждого
    for i, e in enumerate(ev, 1):
        if "message" in e:
            conv.append(e["message"])
            line_of.append(i)
    return ev, conv, line_of


def end_of_log(ev):
    end = ev[-1] if ev[-1].get("call") == "end" else {}
    rec = {k: v for k, v in end.items() if k not in ("event", "call")}
    by_task = rec.get("reason") not in (None, "stopped") and rec.get("detail") != "repeated reply"
    return rec, by_task


def alf_episode(bridge, ev, sent_replies, state, diverge):
    """Задача ALF из записи: start и send отдают сообщения, которые записаны после соответствующего вызова."""
    sends, cur = [], None
    for e in ev:
        if e["event"] == "bridge" and e["call"] in ("start", "send"):
            cur = {"messages": list(e.get("not_shown") or []), "shown": []}
            sends.append(cur)
        elif e["event"] == "env" and cur is not None:
            cur["shown"].append(e["message"])
    end_rec, by_task = end_of_log(ev)

    class Bench:
        def start(self):
            s = sends[0]
            return {"messages": [TASK_SYSTEM] + s["shown"] + s["messages"], "status": "running", "finish": False}

        def interact(self, reply):
            i = state["send"]
            state["send"] += 1
            if i + 1 >= len(sends):
                diverge(kind="bridge", call=state["call"], text="the harness hands the task a reply the log does not have",
                        new=[reply], old=[])
            if key(reply) != key(sent_replies[i]):
                diverge(kind="bridge", call=state["call"], text="the reply handed to the task differs",
                        new=[reply], old=[sent_replies[i]])
            rec = sends[i + 1]
            fin = i + 2 == len(sends) and by_task
            return {"messages": rec["shown"] + rec["messages"],
                    "status": end_rec.get("status", "running") if fin else "running", "finish": fin}

        def end_of(self, status):
            return end_rec

    return bridge.Episode(Bench())


OUT_HEAD, OUT_TAIL = "Output:\n```\n", "```\n\n"


def app_episode(bridge, ev, sent_replies, state, diverge):
    """Цикл AppWorld из записи: fill подставляет записанные значения слотов, execute отдаёт записанный вывод."""
    import re
    slots = next((e.get("slots") for e in ev if e.get("call") == "fill"), None) or {}
    execs = []
    for i, e in enumerate(ev):
        if e["event"] == "bridge" and e.get("call") == "execute":
            out = None
            for f in ev[i + 1:]:
                if f["event"] == "env":
                    c = f["message"]["content"]
                    out = c[len(OUT_HEAD):-len(OUT_TAIL)] if c.startswith(OUT_HEAD) and c.endswith(OUT_TAIL) else c
                    break
                if f["event"] == "bridge" or f["event"] == "model":
                    break
            execs.append({"code": e["code"], "out": out})
    end_rec, by_task = end_of_log(ev)

    class Episode:
        def __init__(self):
            self.steps, self.finished, self.end = 0, False, None

        def fill(self, text):
            def sub(m):
                name = m.group(1).strip()
                if name not in slots:
                    diverge(kind="bridge", call=state["call"], text=f"the prompt asks for slot {{{{ {name} }}}}, not in the log",
                            new=[], old=[])
                return slots[name]
            return re.sub(r"{{(.*?)}}", sub, text)

        def execute(self, code):
            i = self.steps
            if i >= len(execs):
                diverge(kind="bridge", call=state["call"], text="the harness runs code the log does not have",
                        new=[{"role": "code", "content": code}], old=[])
            if code != execs[i]["code"]:
                diverge(kind="bridge", call=state["call"], text="the code run in the task differs",
                        new=[{"role": "code", "content": code}], old=[{"role": "code", "content": execs[i]["code"]}])
            self.steps += 1
            state["send"] += 1
            if i + 1 == len(execs) and by_task:
                self.finished, self.end = True, end_rec
            return execs[i]["out"]

    return Episode()


def play(bench, src, log, at=None, cover=None, watch=None):
    sys.path[:0] = [src]
    import bridge
    import harness

    ev, conv, line_of = load_log(log)
    model_pos = [i for i, m in enumerate(conv) if m["role"] == "assistant" and ev[line_of[i] - 1]["event"] == "model"]
    trace = {"hooks": [], "div": None}
    stopped = end_of_log(ev)[0].get("reason") == "stopped"
    state = {"call": 0, "send": 0}

    def diverge(**kw):
        trace["div"] = kw
        raise Diverged()

    def llm(messages, tools=None):
        k = state["call"]
        state["call"] += 1
        if k >= len(model_pos):
            if stopped and [key(m) for m in messages] == [key(m) for m in conv]:
                raise Diverged()   # запись оборвал стенд (контекст, время) ровно на этом запросе: расхождения нет
            diverge(kind="model", call=k + 1, text="the harness asks the model once more; the log has no reply here",
                    at=len(conv), new=messages[len(conv):] or messages[-1:], old=[])
        want = conv[:model_pos[k]]
        if [key(m) for m in messages] != [key(m) for m in want]:
            j = next((j for j, (a, b) in enumerate(zip(messages, want)) if key(a) != key(b)), min(len(messages), len(want)))
            extra = {"new_all": messages, "old_all": want} if k == 0 else {}
            # 11.11, для сводки: сколько шагов задачи (execute / send) было в логе до этого вызова и сколько сделал харнесс
            # сейчас; чьё сообщение стояло в логе на месте расхождения и перед ним (env / harness / model)
            steps_log = sum(1 for e in ev[:line_of[model_pos[k]] - 1] if e["event"] == "bridge" and e.get("call") in ("execute", "send"))
            diverge(kind="model", call=k + 1, text="what the model sees differs from the log", at=j,
                    new=messages[j:j + 3], old=want[j:j + 3] or [conv[model_pos[k]]], bench=bench,
                    ran_log=steps_log, ran_now=state["send"], was=ev[line_of[j] - 1]["event"] if j < len(want) else "model",
                    prev=ev[line_of[j - 1] - 1]["event"] if j else None, **extra)
        reply = json.loads(key(conv[model_pos[k]]))
        if bench == "app" and (reply.get("content") or "").endswith("\n\n"):
            reply["content"] = reply["content"][:-2]   # в логе ответ после обрезки харнессом, с его "\n\n"
        return reply

    class Hooks:
        def __getattr__(self, name):
            fn = getattr(real_hooks, name)
            if not callable(fn):
                return fn

            def wrapped(*a, **kw):
                rec = {"call": state["call"] + 1, "hook": name}
                try:
                    out = fn(*a, **kw)
                    rec["out"] = out if out is None or isinstance(out, (dict, str, list)) else repr(out)
                    return out
                except Exception as e:
                    import traceback
                    tb = traceback.extract_tb(e.__traceback__)[-1]
                    rec["raised"] = f"{type(e).__name__}: {e} (src/{Path(tb.filename).name}:{tb.lineno})"
                    raise
                finally:
                    trace["hooks"].append(rec)
            wrapped.__name__ = name
            return wrapped

    real_hooks = harness.hooks
    if at:   # --at K: вызовы функций src/harness.py и src/hooks.py перед вызовом модели K, со значениями
        trace["at"], depth = [], [0]

        def watch(mod, name, fn):
            def w(*a, **kw):
                rec = None
                if state["call"] + 1 == at:
                    args = [val(x) for x in a] + [f"{n}={val(v)}" for n, v in kw.items()]
                    rec = {"f": f"{mod.__name__}.{name}", "args": args, "depth": depth[0]}
                    trace["at"].append(rec)
                depth[0] += 1
                try:
                    out = fn(*a, **kw)
                except Exception as e:
                    if rec:
                        rec["raised"] = f"{type(e).__name__}: {e}"
                    raise
                finally:
                    depth[0] -= 1
                if rec:
                    rec["ret"] = val(out)
                return out
            w.__name__ = name
            return w
        import types
        for mod in (harness, real_hooks):
            for name, fn in list(vars(mod).items()):
                if isinstance(fn, types.FunctionType) and fn.__module__ == mod.__name__ and name != "run":
                    setattr(mod, name, watch(mod, name, fn))
    harness.hooks = Hooks()
    sent = [conv[i] for i in model_pos]
    ep = {"alf": alf_episode, "app": app_episode}[bench](bridge, ev, sent, state, diverge)
    try:
        # защита стенда — только если запись ею и кончилась: иначе тогда её не было (B8, r5app run 19)
        guarded = end_of_log(ev)[0].get("detail") == "repeated reply"
        if cover is not None:   # 6.11: строки src, выполненные за проигрыш (до расхождения или до конца лога)
            root = os.path.realpath(src) + os.sep
            last = {}
            shape = bool((watch or {}).get("__shape__"))   # 6.11: у длинной строки — начало, конец и размер

            def rv(v, n):
                if not shape or not isinstance(v, str) or len(repr(v)) <= n:
                    return repr(v)[:n]
                k = v.count("\n") + 1
                return (repr(v[:n // 2]) + " … " + repr(v[-(n // 4):])
                        + f" ({len(v)} chars, {k} line{'s' if k > 1 else ''})")
            def tracer(frame, event, arg):
                f = os.path.realpath(frame.f_code.co_filename)
                if not f.startswith(root) or frame.f_code.co_name == "<genexpr>":   # шаги генератора — не новые выполнения строки
                    return None
                if event == "line":
                    if last.get(id(frame)) == frame.f_lineno:   # шаги цикла внутри одной строки — одно выполнение
                        return tracer
                    last[id(frame)] = frame.f_lineno
                    c = cover.setdefault(f[len(root):], {})
                    c[frame.f_lineno] = c.get(frame.f_lineno, 0) + 1
                    exprs = (watch or {}).get(f"{f[len(root):]}:{frame.f_lineno}")
                    if exprs:   # 6.11 --watch: значения выражений строки на её последнем выполнении
                        vals = {}
                        for e in exprs:
                            try:
                                v = eval(e, {**frame.f_globals, **frame.f_locals})   # одно пространство: генераторам видны локальные
                                if isinstance(v, (list, tuple)) and len(v) > 3:   # длинный список — его хвост: туда смотрит проверка
                                    v = f"[... {len(v)} items, last 3: " + ", ".join(rv(x, 60) for x in v[-3:]) + "]"
                                    vals[e] = v if shape else v[:240]
                                else:
                                    vals[e] = rv(v, 160)
                            except Exception as x:  # noqa: BLE001
                                vals[e] = f"<{type(x).__name__}>"
                        cover.setdefault("__val__", {})[f"{f[len(root):]}:{frame.f_lineno}"] = {
                            "call": state["call"], "vals": vals}
                elif event == "return":
                    last.pop(id(frame), None)   # что вернула функция src и с какой строки: "__ret__" -> {файл: {строка: {значение: раз}}}
                    v = arg if isinstance(arg, (bool, int, type(None))) else type(arg).__name__
                    c = cover.setdefault("__ret__", {}).setdefault(f[len(root):], {}).setdefault(frame.f_lineno, {})
                    c[repr(v)] = c.get(repr(v), 0) + 1
                return tracer
            sys.settrace(tracer)
        try:
            out = harness.run(ep, bridge.guard(ep, llm) if guarded else llm)
        finally:
            if cover is not None:
                sys.settrace(None)
        if [key(m) for m in out] != [key(m) for m in conv]:
            j = next((j for j, (a, b) in enumerate(zip(out, conv)) if key(a) != key(b)), min(len(out), len(conv)))
            text = ("the harness ends the episode here; the log goes on" if len(out) < len(conv) else
                    "the harness adds messages after the log's last one" if j == len(conv) else
                    "the conversation at the end differs from the log")
            diverge(kind="end", call=state["call"], text=text, at=j, new=out[j:j + 3], old=conv[j:j + 3])
    except Diverged:
        pass
    except bridge.Loop:
        if state["call"] < len(model_pos):
            trace["div"] = {"kind": "end", "call": state["call"], "text": "the stand's guard ends the episode here; the log goes on",
                            "new": [], "old": [conv[model_pos[state["call"]]]]}
    except Exception:
        import traceback
        tb = [f for f in traceback.extract_tb(sys.exc_info()[2]) if not f.filename.endswith("rerun.py")]
        e = sys.exc_info()[1]
        text = "\n".join(f"  src/{Path(f.filename).name}:{f.lineno} {f.name}: {(f.line or '').strip()}" for f in tb[-3:])
        trace["div"] = {"kind": "crash", "call": state["call"], "text": f"{type(e).__name__}: {e}\n{text}", "new": [], "old": []}
    d = trace["div"]
    if d is not None:
        at = d.get("at")
        d["line"] = line_of[at] if at is not None and at < len(line_of) else None
    return trace


def worker(bench, src, logs, runs=None, at=None, cover=None, watch=None):
    """Все прогоны вида на одном src, в этом же процессе: модули src перезагружаются для каждого прогона."""
    sys.dont_write_bytecode = True
    out = {}
    for p in sorted(Path(logs).glob("run_*.jsonl"), key=lambda p: int(p.stem.split("_")[1])):
        if runs is not None and p.stem.split("_")[1] not in runs:
            continue
        saved = list(sys.path)
        for m in ("harness", "bridge", "hooks"):
            sys.modules.pop(m, None)
        try:
            c = cover.setdefault(p.stem.split("_")[1], {}) if cover is not None else None
            out[p.stem.split("_")[1]] = play(bench, src, str(p), at, c, watch)
        finally:
            sys.path[:] = saved
            for m in ("harness", "bridge", "hooks"):
                sys.modules.pop(m, None)
    return out


# ---------------------------------------------------------------- вывод
def results(logs):
    p = Path(logs) / "results.jsonl"
    if not p.exists():
        return {}
    return {str(json.loads(l)["run"]): json.loads(l) for l in open(p)}


def hook_notes(new, old):
    """Хуки, которые на старом src отвечали иначе (до первого расхождения)."""
    o = {(h["call"], h["hook"]): h for h in old}
    notes = []
    for h in new:
        p = o.get((h["call"], h["hook"]))
        a = (h.get("out"), h.get("raised"))
        b = (p.get("out"), p.get("raised")) if p else (None, None)
        if a != b:
            notes.append((h, p))
    return notes


def fmt_hook(h):
    if h is None:
        return "not called"
    if h.get("raised"):
        return f"raised {h['raised']}"
    out = h.get("out")
    return "None" if out is None else (out if isinstance(out, str) else json.dumps(out, ensure_ascii=False))[:200]


def prompt_diff(d, limit=12):
    import difflib
    def lines(ms):
        return [f"{m['role']}: {x}" for m in ms for x in (m.get("content") or "").splitlines()]
    out = [l for l in difflib.unified_diff(lines(d["old_all"]), lines(d["new_all"]), lineterm="", n=0)
           if l[:1] in "+-" and not l.startswith(("+++", "---"))]
    more = f"\n  … {len(out) - limit} more changed lines" if len(out) > limit else ""
    return "\n".join("  " + l[:160] for l in out[:limit]) + more


def norm(s):
    """Для группировки: строки в кавычках и числа не различаем."""
    import re
    s = s.replace('\\"', "'")
    return re.sub(r"\d+", "N", re.sub(r'"[^"\n]*"|\'[^\'\n]*\'', '"…"', s))


WORDS = {"app": {"ran": "ran the model's code", "got": "the output", "norun": "does not run this code",
                 "norun_log": "did not run this code", "done": "The code is run"},
         "alf": {"ran": "sent the model's action to the task", "got": "the answer", "norun": "does not send this action",
                 "norun_log": "did not send this action", "done": "The action is sent"}}


def said(m, n):
    s = m.get("content") or ""
    if s.startswith(OUT_HEAD) and s.endswith(OUT_TAIL):
        s = s[len(OUT_HEAD):-len(OUT_TAIL)]
    s = s.strip().replace("\n", "\\n")
    return '"' + s[:n] + ("…" if len(s) > n else "") + '"'


def event_of(d):
    """Что харнесс делает иначе на месте расхождения — по логу и повтору, без толкования. None: прежняя форма «- / +»."""
    if d is None or d["kind"] != "model" or d["call"] == 1 or "was" not in d or not d["old"]:
        return None
    if not d["new"]:
        return "removed" if d["was"] == "harness" else None
    if d["ran_log"] > d["ran_now"] and d["was"] == "env":
        return "skipped"
    if d["was"] == "harness":
        return "reworded" if d["prev"] == "model" else "reworded_after"
    return "added" if d["was"] == "model" else None


def event_text(d, first):
    """Одно событие полными предложениями: что было в логе, что харнесс делает теперь. first — номер прогона той же
    группы, уже описанного выше (тогда коротко), или None."""
    c, w = event_of(d), WORDS[d["bench"]]
    old = said(d["old"][0], WAS_CHARS)
    new = said(d["new"][0], ADDED_CHARS) if d["new"] else ""
    if c == "skipped":
        if first:
            return f"The same as run {first}: in the log the harness {w['ran']} and {w['got']} was {old}. Now the harness {w['norun']}."
        return (f"In the log the harness {w['ran']} and the model got {w['got']}: {old}. Now the harness "
                f"{w['norun']}. The model gets this message instead: {new}")
    if c == "reworded":
        return (f"The harness does the same as in the log: in the log it also {w['norun_log']}. Only the text of its "
                f"message is different. In the log: {said(d['old'][0], 300)} Now: {new}")
    if c == "reworded_after":
        return (f"{w['done']} as in the log. The message the harness gives the model after it is different. "
                f"In the log: {said(d['old'][0], 300)} Now: {new}")
    if c == "removed":
        return f"In the log the harness gave the model this message here: {said(d['old'][0], 300)} Now it does not."
    if first:
        return f"The same as run {first}: the harness gives the model a message that the log does not have here."
    return f"Up to this point the harness does the same as in the log. Then it gives the model a message that the log does not have: {new}"


def report_plain(new, old, res, runs):
    """11.11, сводка после правки явными предложениями. Прежняя сводка печатала только новое сообщение («+ user: …»):
    шаг, который в логе исполнился, а теперь не исполняется, и смена текста прежнего сообщения выглядели одинаково."""
    ok = {r: bool(res.get(r, {}).get("ok")) for r in runs}
    ev = {r: event_of(new[r]["div"]) for r in runs}
    same = [r for r in runs if new[r]["div"] is None]
    text_only = [r for r in runs if ev[r] in ("reworded", "reworded_after")]
    n = len(runs) - len(same) - len(text_only)
    head = f"{len(runs)} runs replayed on your src/: {n} go differently from the log"
    if text_only:
        head += f", {len(text_only)} differ{'s' if len(text_only) == 1 else ''} only in the text of a message from the harness"
    head += (f", {len(same)} go{'es' if len(same) == 1 else ''} exactly as in the log. Each run is replayed up to the first place "
             "where the harness does something different from the log; what the model would do after that is not known: "
             "the replay only has the model's replies from the log.")
    out, firsts = [head], {}
    for want, title in ((True, "Passed runs (in the log the task was solved):"), (False, "Failed runs:")):
        sec = [r for r in runs if ok[r] == want]
        if not sec:
            continue
        out += ["", title]
        groups = {}
        for r in sec:
            d = new[r]["div"]
            if d is None:
                continue
            if ev[r] is None:
                out.append("- " + report_diff(new, old, res, [r], detail=True).replace("\n", "\n  "))
                continue
            groups.setdefault((ev[r], norm(said(d["new"][0], ADDED_CHARS)) if d["new"] else ""), []).append(r)
        for k, rs in sorted(groups.items(), key=lambda g: g[0][0].startswith("reworded")):   # смена одного текста — после изменений поведения
            for r in rs[:SAME_RUNS]:
                d = new[r]["div"]
                line = f"- run {r}, model call {d['call']}. " + event_text(d, firsts.get(k))
                if k not in firsts:
                    firsts[k] = r
                    for h, p in (hook_notes(new[r]["hooks"], old[r]["hooks"]) if old else [])[:1]:
                        line += f"\n  Hook {h['hook']} returns {fmt_hook(h)} here; with the original src/ it returned {fmt_hook(p)}."
                out.append(line)
            rest = rs[SAME_RUNS:]
            if rest:
                out.append(f"- run{'s' if len(rest) > 1 else ''} " + ", ".join(f"{r} (model call {new[r]['div']['call']})" for r in rest)
                           + f". The same as run {firsts[k]}.")
        quiet = [r for r in sec if new[r]["div"] is None]
        if quiet:
            out.append(f"- run{'s' if len(quiet) > 1 else ''} " + ", ".join(quiet) + f". Go{'es' if len(quiet) == 1 else ''} exactly as in the log.")
    return "\n".join(out)


def report(new, old, res, runs, detail):
    if not detail and any(event_of(new[r]["div"]) for r in runs):
        return report_plain(new, old, res, runs)
    return report_diff(new, old, res, runs, detail)


def report_diff(new, old, res, runs, detail):
    """detail=False: одна строка на группу прогонов с одинаковым (с точностью до кавычек и чисел) расхождением;
    True: ещё номер вызова, строка лога и что было в логе."""
    groups = {}
    for r in runs:
        t = new[r]
        d = t["div"]
        notes = hook_notes(t["hooks"], old[r]["hooks"]) if old else []
        if d is None:
            head, body = "no changes (same as the log to the end)", ""
        elif d["kind"] == "model" and d["call"] == 1:
            head, body = "the prompt differs from the log, so nothing after it can be compared:", "\n" + prompt_diff(d)
        elif d["kind"] == "crash":
            head, body = "the harness crashes" + (f" at model call {d['call']}" if detail else ""), ": " + d["text"].strip()
        else:
            head = "diverges at model call " + (str(d["call"]) + (f" (log line {d['line']})" if d.get("line") else "") if detail else "{calls}")
            head += f": {d['text']}"
            body = ""
            if detail or d["kind"] == "bridge":
                body += "".join(f"\n  - {short(m)}" for m in d["old"][:2])
            body += "".join(f"\n  + {short(m, ADDED_CHARS)}" for m in d["new"][:3])
        seen = {}
        for h, p in notes:
            s = f"hook {h['hook']}" + (f" at model call {h['call']}" if detail else "") + f": {fmt_hook(h)} (was {fmt_hook(p)})"
            seen[s] = seen.get(s, 0) + 1
        for s, n in list(seen.items())[:3]:
            body += f"\n  {s}" + (f" ×{n}" if detail and n > 1 else "")
        g = groups.setdefault(norm(head + body), {"head": head, "body": body, "tags": [], "calls": []})
        g["tags"].append((r, bool(res.get(r, {}).get("ok"))))
        g["calls"].append(str(d["call"]) if d else "")
    out = []
    for g in groups.values():
        calls = sorted(set(g["calls"]), key=lambda c: int(c or 0))
        if len(calls) == 1:
            head = g["head"].replace("{calls}", calls[0])
        else:   # 10.11: какой вызов у какого прогона, проваленные и удачные порознь
            by = [", ".join(f"run {r} at {c}" for (r, ok), c in zip(g["tags"], g["calls"]) if ok == want) for want in (False, True)]
            head = g["head"].replace("at model call {calls}", "at model call: " + "; ".join(f"{n} — {x}" for n, x in zip(("failed", "passed"), by) if x))
        ex = " (e.g. run " + g["tags"][0][0] + ")" if len(g["tags"]) > 1 and g["body"] and norm(g["body"]) != g["body"] else ""
        out.append(runs_label(g["tags"], len(runs)) + ": " + head + ex + g["body"])
    return "\n".join(out)


def report_at(r, t, log, at, ok):
    """--at K: что было в логе перед вызовом модели K и вызовы функций src с их значениями."""
    ev, conv, line_of = load_log(log)
    pos = [i for i, m in enumerate(conv) if m["role"] == "assistant" and ev[line_of[i] - 1]["event"] == "model"]
    d = t["div"]
    head = f"run {r} ({'passed' if ok else 'failed'})"
    if at > len(pos) + 1:
        return f"{head}: the log has {len(pos)} model calls, there is no model call {at}"
    if d is not None and d["call"] < at:
        return (f"{head}: the replay stops at model call {d['call']}, before model call {at}; see python3 tests/rerun.py {r}")
    j = pos[at - 1] if at <= len(pos) else len(conv)
    line = line_of[j] if j < len(line_of) else None
    out = [f"{head}, before model call {at}" + (f" (log line {line})" if line else "") + ":",
           "  the log just before it:"] + [f"    {short(m)}" for m in conv[max(0, j - 2):j]]
    calls = t.get("at") or []
    out.append("  calls of the functions in src/harness.py and src/hooks.py, with the values they got and returned:"
               if calls else "  no function of src/harness.py or src/hooks.py is called there")
    seen = set()
    for c in calls[:40]:
        args = []
        for x in c["args"]:
            args.append(x if len(x) < 40 or x not in seen else "<same as above>")
            seen.add(x)
        s = f"{c['f']}({', '.join(args)})"
        ret = c.get("ret")
        ret = ret if ret is None or len(ret) < 40 or ret not in seen else "<same as above>"
        seen.add(c.get("ret"))
        s = (s if len(s) <= 700 else s[:700] + "…)") + (f" raised {c['raised']}" if "raised" in c else f" -> {ret}")
        out.append("    " + "  " * c["depth"] + s)
    if len(calls) > 40:
        out.append(f"    ... {len(calls) - 40} more calls")
    if d is not None and d["call"] == at:
        out.append(f"  at this call the replay stops: {d['text']}; see python3 tests/rerun.py {r}")
    return "\n".join(out)


def runs_label(tags, total):
    """[(run, ok)] -> 'runs 1, 4, 6 (2 failed, 1 passed)' или 'all 30 runs (…)'."""
    ok = sum(1 for _, o in tags if o)
    head = f"all {total} runs" if len(tags) == total and total > 1 else ("run " if len(tags) == 1 else "runs ") + ", ".join(r for r, _ in tags)
    return f"{head} ({len(tags) - ok} failed, {ok} passed)" if len(tags) > 1 else f"{head} ({'passed' if ok else 'failed'})"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bench", choices=["alf", "app"], required=True)
    ap.add_argument("--src", required=True)
    ap.add_argument("--logs", required=True)
    ap.add_argument("--old", help="the src the logs were recorded on, to compare what the hooks return")
    ap.add_argument("--at", type=int, help="with one run N: the calls of the functions in src before model call K, with their values")
    ap.add_argument("--json", action="store_true", help="where each run diverges, as json")
    ap.add_argument("--cover", action="store_true", help="with --json: how many times each line of src ran")
    ap.add_argument("--watch", help="with --cover: json {\"file:line\": [expressions]}: their values the last time that line ran")
    ap.add_argument("runs", nargs="*")
    a = ap.parse_args()
    if a.json:
        cov = {} if a.cover else None
        new = worker(a.bench, os.path.abspath(a.src), a.logs, a.runs or None, cover=cov,
                     watch=json.loads(a.watch) if a.watch else None)
        div = {r: (None if t["div"] is None else {"kind": t["div"].get("kind"), "call": t["div"].get("call"),
                                                   "text": str(t["div"].get("text", ""))[:600]})
               for r, t in new.items()}
        print(json.dumps({"div": div, "cover": cov} if a.cover else div))
        return
    if a.at:
        assert len(a.runs) == 1, "--at needs one run"
        t = worker(a.bench, os.path.abspath(a.src), a.logs, a.runs, a.at)[a.runs[0]]
        ok = bool(results(a.logs).get(a.runs[0], {}).get("ok"))
        print(report_at(a.runs[0], t, str(Path(a.logs) / f"run_{a.runs[0]}.jsonl"), a.at, ok))
        return
    new = worker(a.bench, os.path.abspath(a.src), a.logs)
    old = worker(a.bench, os.path.abspath(a.old), a.logs) if a.old else None
    runs = a.runs or list(new)
    print(report(new, old, results(a.logs), runs, detail=bool(a.runs)))


if __name__ == "__main__":
    main()
