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
            if i + 1 == len(execs) and by_task:
                self.finished, self.end = True, end_rec
            return execs[i]["out"]

    return Episode()


def play(bench, src, log):
    sys.path[:0] = [src]
    import bridge
    import harness

    ev, conv, line_of = load_log(log)
    model_pos = [i for i, m in enumerate(conv) if m["role"] == "assistant" and ev[line_of[i] - 1]["event"] == "model"]
    trace = {"hooks": [], "div": None}
    state = {"call": 0, "send": 0}

    def diverge(**kw):
        trace["div"] = kw
        raise Diverged()

    def llm(messages, tools=None):
        k = state["call"]
        state["call"] += 1
        if k >= len(model_pos):
            diverge(kind="model", call=k + 1, text="the harness asks the model once more; the log has no reply here",
                    at=len(conv), new=messages[len(conv):] or messages[-1:], old=[])
        want = conv[:model_pos[k]]
        if [key(m) for m in messages] != [key(m) for m in want]:
            j = next((j for j, (a, b) in enumerate(zip(messages, want)) if key(a) != key(b)), min(len(messages), len(want)))
            extra = {"new_all": messages, "old_all": want} if k == 0 else {}
            diverge(kind="model", call=k + 1, text="what the model sees differs from the log", at=j,
                    new=messages[j:j + 3], old=want[j:j + 3] or [conv[model_pos[k]]], **extra)
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
            return wrapped

    real_hooks = harness.hooks
    harness.hooks = Hooks()
    sent = [conv[i] for i in model_pos]
    ep = {"alf": alf_episode, "app": app_episode}[bench](bridge, ev, sent, state, diverge)
    try:
        out = harness.run(ep, bridge.guard(ep, llm))
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


def worker(bench, src, logs):
    """Все прогоны вида на одном src, в этом же процессе: модули src перезагружаются для каждого прогона."""
    sys.dont_write_bytecode = True
    out = {}
    for p in sorted(Path(logs).glob("run_*.jsonl"), key=lambda p: int(p.stem.split("_")[1])):
        saved = list(sys.path)
        for m in ("harness", "bridge", "hooks"):
            sys.modules.pop(m, None)
        try:
            out[p.stem.split("_")[1]] = play(bench, src, str(p))
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
    return "None" if h.get("out") is None else json.dumps(h.get("out"), ensure_ascii=False)[:200]


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


def report(new, old, res, runs, detail):
    """detail=False: одна строка на группу прогонов с одинаковым (с точностью до кавычек и чисел) расхождением;
    True: ещё номер вызова, строка лога и что было в логе."""
    groups = {}
    for r in runs:
        t = new[r]
        d = t["div"]
        notes = hook_notes(t["hooks"], old[r]["hooks"]) if old else []
        if d is None:
            head, body = "same as the log to the end", ""
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
            body += "".join(f"\n  + {short(m)}" for m in d["new"][:3])
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
        head = g["head"].replace("{calls}", calls[0] if len(calls) == 1 else "(" + ", ".join(calls) + ")")
        ex = " (e.g. run " + g["tags"][0][0] + ")" if len(g["tags"]) > 1 and g["body"] and norm(g["body"]) != g["body"] else ""
        out.append(runs_label(g["tags"], len(runs)) + ": " + head + ex + g["body"])
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
    ap.add_argument("--old", help="src, на котором записаны логи: для сравнения ответов хуков")
    ap.add_argument("runs", nargs="*")
    a = ap.parse_args()
    new = worker(a.bench, os.path.abspath(a.src), a.logs)
    old = worker(a.bench, os.path.abspath(a.old), a.logs) if a.old else None
    runs = a.runs or list(new)
    print(report(new, old, results(a.logs), runs, detail=bool(a.runs)))


if __name__ == "__main__":
    main()
