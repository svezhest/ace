"""Разбор лога сессии исследователя (без модели).

python3 analyze.py logs/<session>.jsonl [--transcript out.md] [--json out.json]

Для каждого принятого report: на какие выводы bash опираются его ссылки evidence и видны ли эти выводы модели в момент
report (не убраны очисткой / сжатием). Класс ссылки: V — строки показаны во выводе, который ещё виден; C — показаны
только в убранных выводах; N — ни в одном выводе не показаны. Класс report: V — все ссылки V; P — есть V и C/N;
C — нет V, есть C; N — все N. Сопоставление приблизительное: строка считается показанной, если её кусок (сырой
строки JSON или раскодированного текста content) найден в выводе команды, которая упоминает этот файл (имя в команде
или в выводе) либо читает по шаблону (*, -r).
"""
import argparse
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))


def load(path):
    return [json.loads(l) for l in open(path) if l.strip()]


def _texts(line):
    raw = line.rstrip("\n")
    try:
        obj = json.loads(raw)
    except Exception:
        obj = None
    if isinstance(obj, dict):
        texts = [obj["content"]] if isinstance(obj.get("content"), str) else []
        texts += [c.get("function", {}).get("arguments", "") for c in obj.get("tool_calls") or []]
        return [t for t in texts if t.strip()]
    return [raw.strip()] if raw.strip() else []


_PROBE_CACHE = {}


def probes(lines, idx, path=""):
    """Куски строки idx файла, которые не встречаются в других строках этого файла (сырые и в экранировании JSON)."""
    key = (path, idx)
    if key in _PROBE_CACHE:
        return _PROBE_CACHE[key]
    others = "\n".join(t for k, l in enumerate(lines) if k != idx for t in _texts(l))
    out = []
    for t in _texts(lines[idx]):
        if len(t) < 40:
            if t not in others and len(t) >= 6:
                out.append(t)
            continue
        for a in range(0, len(t) - 30, 15):
            chunk = t[a:a + 40]
            if chunk not in others:
                out.append(chunk)
            if len(out) >= 6:
                break
    out += [json.dumps(c, ensure_ascii=False)[1:-1] for c in out]
    _PROBE_CACHE[key] = [p for p in dict.fromkeys(out) if p]
    return _PROBE_CACHE[key]


def parse_ev(e):
    m = re.match(r"([^:\s]+):L?(\d+)(?:\s*-\s*L?(\d+))?(?:[:\s].*)?$", e, re.S)
    if not m:
        return e, None, None
    return m.group(1), int(m.group(2)), int(m.group(3) or m.group(2))


def candidate(cmd, shown, path):
    b = os.path.basename(path)
    return b in cmd or b in shown or "*" in cmd or re.search(r"\s-[a-zA-Z]*r", cmd) or "xargs" in cmd


def analyze(logp):
    recs = load(logp)
    meta = recs[0]
    view = os.path.join(HERE, "views", meta["view"])
    calls = {}          # call no -> {cmd, shown, visible}
    events = []         # хронология для транскрипта
    selfwritten = []    # (call no, text) заметки / сводки / текст модели
    reports = []
    n = 0
    for r in recs[1:]:
        t = r.get("type")
        if t == "note" and r.get("cleared_calls") is not None:
            for c in r["cleared_calls"]:
                if c in calls:
                    calls[c]["visible"] = False
            events.append(("clear", n, r))
        elif t == "compact":
            for c in r["removed_calls"]:
                if c in calls:
                    calls[c]["visible"] = False
            selfwritten.append((n, "summary", r["summary"]))
            events.append(("compact", n, r))
        elif t == "turn":
            events.append(("turn", n, r))
            if r.get("content"):
                selfwritten.append((n, "content", r["content"]))
            for res in r.get("results", []):
                n += 1
                res["_no"] = n
                name = res.get("name")
                try:
                    args = json.loads(res.get("arguments") or "{}")
                except Exception:
                    args = {}
                if name == "bash":
                    shown = res.get("shown")
                    if shown == "(= output_head)":
                        shown = res.get("output_head", "")
                    calls[n] = {"cmd": args.get("command", ""), "shown": shown or "", "visible": True,
                                "turn": r["i"]}
                elif name == "note":
                    selfwritten.append((n, "note", args.get("text", "")))
                elif name == "report" and res.get("recorded"):
                    reports.append(analyze_report(n, args, res, calls, view, selfwritten))
        elif t == "end":
            events.append(("end", n, r))
    return meta, recs[-1] if recs[-1].get("type") == "end" else None, reports, events, calls


def analyze_report(n, args, res, calls, view, selfwritten):
    ev = args.get("evidence")
    if isinstance(ev, str):
        ev = [ev]
    items = []
    for e in ev or []:
        path, a, b = parse_ev(str(e).strip().lstrip("./"))
        full = os.path.join(view, path)
        if not os.path.isfile(full):
            items.append({"ev": e, "cls": "?", "from": []})
            continue
        lines = open(full, errors="replace").read().split("\n")
        if a is None:
            a, b = 1, len(lines)
        b = min(b, a + 14)
        vis, clr = set(), set()
        for ln in range(a, b + 1):
            if ln - 1 >= len(lines):
                break
            ps = probes(lines, ln - 1, full)
            if not ps:
                continue
            for c, info in calls.items():
                if c >= n or not candidate(info["cmd"], info["shown"], path):
                    continue
                if any(p in info["shown"] for p in ps):
                    (vis if info["visible"] else clr).add(c)
        cls = "V" if vis else "C" if clr else "N"
        own = any(os.path.basename(path) in txt for _, _, txt in selfwritten)
        items.append({"ev": e, "cls": cls, "vis": sorted(vis), "clr": sorted(clr), "own_mention": own})
    cs = {i["cls"] for i in items}
    rc = ("V" if cs == {"V"} else "P" if "V" in cs else "C" if "C" in cs else "N")
    return {"call": n, "kind": args.get("kind"), "obs": args.get("observation"), "items": items, "cls": rc,
            "final": res.get("recorded") is not None and False}


def transcript(meta, end, events, calls, reports, out, maxout=2500):
    rep_by_call = {r["call"]: r for r in reports}
    with open(out, "w") as f:
        f.write(f"# {meta['view']} policy={meta.get('policy')} runs={meta['runs']}\n\n")
        for kind, n, r in events:
            if kind == "clear":
                f.write(f"\n>>> CLEAR before call {n + 1}: cleared calls {r['cleared_calls']} ({r['text']})\n\n")
            elif kind == "compact":
                f.write(f"\n>>> COMPACT before call {n + 1} ({r['sec']} s, removed calls {r['removed_calls'][0]}..{r['removed_calls'][-1]}):\n"
                        f"SUMMARY:\n{r['summary']}\n\n")
            elif kind == "end":
                f.write(f"\n# END {r['reason']}\n{json.dumps(r['stats'], ensure_ascii=False)}\n")
            else:
                u = r.get("usage") or {}
                f.write(f"## turn {r['i']} ({r.get('sec')} s, prompt {u.get('prompt_tokens')}, gen {u.get('completion_tokens')})\n")
                if r.get("error"):
                    f.write(f"ERROR {r['error']}\n")
                if r.get("content"):
                    f.write(f"[text] {r['content']}\n")
                for res in r.get("results", []):
                    no = res.get("_no")
                    try:
                        args = json.loads(res.get("arguments") or "{}")
                    except Exception:
                        args = {"raw": res.get("arguments")}
                    if res.get("name") == "bash":
                        sh = calls.get(no, {}).get("shown", "")
                        f.write(f"### call {no} bash: {args.get('command')}\n")
                        f.write("```\n" + (sh if len(sh) <= maxout else sh[:maxout] + f"\n...[{len(sh)} chars]") + "\n```\n")
                    elif res.get("name") == "report":
                        rr = rep_by_call.get(no)
                        tag = f"ACCEPTED cls={rr['cls']} " + " ".join(f"{i['ev']}={i['cls']}{i.get('vis') or ''}{i.get('clr') or ''}" for i in rr["items"]) if rr else f"REJECTED {res.get('rejected')}"
                        f.write(f"### call {no} REPORT [{args.get('kind')}] {tag}\n{args.get('observation')}\nevidence: {args.get('evidence')}\n")
                    else:
                        f.write(f"### call {no} {res.get('name')}: {json.dumps(args, ensure_ascii=False)[:1500]}\n")
                if r.get("format_fail"):
                    f.write(f"(format_fail {r['format_fail']})\n")
                f.write("\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("log")
    ap.add_argument("--transcript")
    ap.add_argument("--json")
    a = ap.parse_args()
    meta, end, reports, events, calls = analyze(a.log)
    st = end["stats"] if end else {}
    print(f"policy={meta.get('policy')} runs={meta['runs']} end={end and end['reason']}")
    keys = ["turns", "tool_calls", "bash", "reports_ok", "reports_rejected", "notes", "compactions", "clears",
            "cleared_results", "max_prompt", "model_sec", "repeats", "denied", "no_call", "final_turns", "traces_read"]
    print({k: st.get(k) for k in keys})
    clr = [(n, e[2]["cleared_calls"]) for e in events if e[0] == "clear" for n in [e[1]]]
    print("clears (after call n: cleared calls):", [(n, f"{c[0]}..{c[-1]}" if c else "-") for n, c in clr])
    cmp_ = [(e[1], len(e[2]["removed_calls"]), e[2]["sec"]) for e in events if e[0] == "compact"]
    if cmp_:
        print("compactions (after call n, removed, sec):", cmp_)
    from collections import Counter
    print("report classes:", dict(Counter(r["cls"] for r in reports)))
    for r in reports:
        print(f"- call {r['call']} [{r['kind']}] {r['cls']}: " + "; ".join(
            f"{i['ev']}={i['cls']}" + (f"(vis {i['vis']})" if i.get('vis') else "") + (f"(clr {i['clr']})" if i.get('clr') else "")
            for i in r["items"]))
        print("    " + (r["obs"] or "").replace("\n", " ")[:600])
    if a.transcript:
        transcript(meta, end, events, calls, reports, a.transcript)
    if a.json:
        json.dump({"meta": {k: meta[k] for k in ("view", "policy", "runs")}, "stats": st, "reports": reports},
                  open(a.json, "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
