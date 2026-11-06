"""6.11: проба ответа на повтор команды без целых сессий. Точка — ход сессии писателя (runs/wvar_1104), где bash
получил «This is the same command as tool call N». Контекст из лога до этого хода; ответ на повтор подменяется
вариантом; модель сэмплируется K раз; мерка — есть ли в следующем ходе та же (exact) или почти та же (near) команда.
Варианты: old — как в логе; clean — «already run… tells you nothing new: change the command…» + вывод целиком;
plain — вывод целиком, как в shell; resample — ход перед повтором сэмплируется заново (повтор не исполняется);
cut — обе копии (исходный вызов с выводом и повтор) вырезаны из истории, в конце — заметка харнесса без текста
команды: программы, файлы, что напечатано.
  python3 editor/repeat_probe.py OUT.jsonl [--k 3] [--variants old,clean,plain,resample]"""
import argparse
import difflib
import glob
import hashlib
import json
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from nrhsi import researcher as F  # noqa: E402
from nrhsi.editor import schema as SC  # noqa: E402

H = f"{ROOT}/runs/wvar_1104"
REP = "This is the same command as tool call "
SIMPLE = ("intent", "intent_opt", "rerun_tool", "finish_review", "scratch", "hide_tools")   # иначе другая схема


def norm(c):
    return " ".join((c or "").split())


def cmd_of(call):
    try:
        return norm(json.loads(call["arguments"]).get("command", ""))
    except Exception:  # noqa: BLE001
        return ""


def history(recs, upto, sub=None, cut_assistant=False):
    """Сообщения до хода upto включительно (его результаты — с заменой sub {j: текст}); cut_assistant — без хода upto."""
    meta = recs[0]
    msgs = [{"role": "system", "content": meta["system"]}, {"role": "user", "content": meta["first_user"]}]
    for r in recs[1:]:
        if r.get("type") == "note":
            msgs.append({"role": "user", "content": r["text"]})
        elif r.get("type") == "turn" and r.get("i") is not None and r["i"] <= upto:
            if r["i"] == upto and cut_assistant:
                break
            am = {"role": "assistant", "content": r.get("content") or ""}
            if r.get("tool_calls"):
                am["tool_calls"] = [{"id": f"call_{r['i']}_{j}", "type": "function",
                                     "function": {"name": c["name"], "arguments": c["arguments"]}}
                                    for j, c in enumerate(r["tool_calls"])]
            msgs.append(am)
            for j, res in enumerate(r.get("results") or []):
                txt = sub[j] if (sub and r["i"] == upto and j in sub) else res["shown"]
                msgs.append({"role": "tool", "tool_call_id": f"call_{r['i']}_{j}", "content": txt})
            if r["i"] == upto:
                break
    return msgs


def points():
    seen_ctx, out = set(), []
    for p in sorted(glob.glob(f"{H}/*/logs/*.jsonl")):
        name = p.split("/")[-3]
        sj = glob.glob(f"{H}/{name}/out/*.summary.json")
        if not sj:
            continue
        s = json.load(open(sj[0]))
        if any(str(s.get(k)) == "True" for k in SIMPLE):
            continue
        recs = [json.loads(x) for x in open(p)]
        turns = [r for r in recs if r.get("type") == "turn" and r.get("i") is not None]
        for t in turns:
            for j, (c, res) in enumerate(zip(t.get("tool_calls") or [], t.get("results") or [])):
                if c["name"] != "bash" or not (res.get("shown") or "").startswith(REP):
                    continue
                key = cmd_of(c)
                orig = next(((u["i"], jj, x) for u in turns if u["i"] < t["i"]
                             for jj, (cc, x) in enumerate(zip(u.get("tool_calls") or [], u.get("results") or []))
                             if cc["name"] == "bash" and cmd_of(cc) == key and not (x.get("shown") or "").startswith(REP)), None)
                if orig is None:
                    continue
                ou, oj, orig = orig
                h = hashlib.md5(json.dumps(history(recs, t["i"])[:-1], sort_keys=True).encode()).hexdigest()
                if h in seen_ctx:      # копии одной сессии (пары с общим началом)
                    continue
                seen_ctx.add(h)
                n = int(res["shown"][len(REP):].split(",")[0])
                out.append({"session": name, "turn": t["i"], "j": j, "cmd": key, "n": n, "orig": orig["shown"], "ou": ou, "oj": oj,
                            "recs": recs, "summary": s})
    return out


def variant_sub(pt, v):
    if v == "old":
        return None
    if v == "plain":
        return {pt["j"]: pt["orig"]}
    if v == "clean":
        return {pt["j"]: (f"This command was already run at tool call {pt['n']}, and no file has changed since, so it "
                          f"prints the same as there (repeated below). Running it again tells you nothing new: change "
                          f"the command, or go on from this output.\n{pt['orig']}")}
    raise ValueError(v)


def gist(cmd):
    """Команда без её текста: программы по сегментам конвейера и пути файлов."""
    progs, files = [], []
    first = cmd.split(" <<")[0]                       # тело heredoc и python -c — не программы
    first = re.sub(r"(-c\s+)(['\"]).*", r"\1", first)
    for seg in re.split(r"\|\||&&|[|;]", first):
        w = seg.split()
        if w and w[0] in F.ALLOWED and w[0] not in ("cd", ":") and w[0] not in progs:
            progs.append(w[0])
    for f in re.findall(r"(?:src|logs|tests)/[\w./-]+|\b[\w-]+\.(?:py|md|jsonl)\b", cmd):
        if f not in files:
            files.append(f)
    return ", ".join(progs) + (" on " + ", ".join(files[:4]) if files else "")


def cut(msgs, p):
    """Вырезать вызовы (ou, oj) и (turn, j) с их выводами; пустой ответ ассистента без вызовов — тоже; в конце заметка."""
    res = {m["tool_call_id"]: m["content"] for m in msgs if m["role"] == "tool"}
    drop = {c["id"] for m in msgs if m["role"] == "assistant" for c in m.get("tool_calls") or []   # тот же вывод
            if c["function"]["name"] == "bash" and cmd_of(c["function"]) == p["cmd"]
            and (res.get(c["id"]) == p["orig"] or (res.get(c["id"]) or "").startswith(REP))}
    out = []
    for m in msgs:
        if m["role"] == "tool" and m["tool_call_id"] in drop:
            continue
        if m["role"] == "assistant" and m.get("tool_calls"):
            m = dict(m)
            m["tool_calls"] = [c for c in m["tool_calls"] if c["id"] not in drop]
            if not m["tool_calls"]:
                del m["tool_calls"]
                if not (m.get("content") or "").strip():
                    continue
        out.append(m)
    o = p["orig"].strip()
    o = o if len(o) <= 400 else o[:400] + " …"
    out.append({"role": "user", "content": f"{len(drop)} identical bash calls ({gist(p['cmd'])}) were taken out of this "
                                            f"conversation. Each printed:\n{o}"})
    return out


def judge(calls, cmd):
    cs = [cmd_of(c) for c in calls if c["function"]["name"] == "bash"]
    exact = any(c == cmd for c in cs)
    near = exact or any(difflib.SequenceMatcher(None, c, cmd).ratio() >= 0.9 for c in cs)
    return exact, near, cs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--k", type=int, default=3)
    ap.add_argument("--variants", default="old,clean,plain,resample,cut")
    ap.add_argument("--stand", default="default")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    pts = points()
    print(json.dumps({"points": len(pts), "sessions": len({p["session"] for p in pts})}), flush=True)
    if a.list:
        for p in pts:
            print(p["session"], p["turn"], p["cmd"][:100])
        return
    F.apply_stand(a.stand)
    tools = [SC.BASH_SCHEMA, SC.EDIT_SCHEMA, SC.FINISH_SCHEMA]
    done = set()
    if os.path.exists(a.out):
        for x in open(a.out):
            r = json.loads(x)
            done.add((r["session"], r["turn"], r["j"], r["variant"], r["sample"]))
    with open(a.out, "a") as f:
        for v in a.variants.split(","):
            for p in pts:
                if v == "resample":
                    msgs = history(p["recs"], p["turn"], cut_assistant=True)
                elif v == "cut":
                    msgs = cut(history(p["recs"], p["turn"]), p)
                else:
                    msgs = history(p["recs"], p["turn"], sub=variant_sub(p, v))
                for s in range(a.k):
                    if (p["session"], p["turn"], p["j"], v, s) in done:
                        continue
                    seed = 900_000 + 1000 * s + p["turn"]          # сдвиг от seed сессии
                    t0 = time.time()
                    resp, err = F.chat(msgs, F.TEMP, seed, tools)
                    dt = round(time.time() - t0, 1)
                    u = (resp or {}).get("usage") or {}
                    r, perr = (F.parse_response(resp) if not err else (None, err))
                    calls = (r or {}).get("calls") or []
                    ex, nr, cs = judge(calls, p["cmd"])
                    f.write(json.dumps({"session": p["session"], "turn": p["turn"], "j": p["j"], "variant": v,
                                        "sample": s, "cmd": p["cmd"], "exact": ex, "near": nr, "next_bash": cs,
                                        "next_tools": [c["function"]["name"] for c in calls],
                                        "content": ((r or {}).get("content") or "")[:400], "error": err or perr, "sec": dt,
                                        "prompt_tokens": u.get("prompt_tokens"),
                                        "cached": (u.get("prompt_tokens_details") or {}).get("cached_tokens")},
                                       ensure_ascii=False) + "\n")
                    f.flush()


if __name__ == "__main__":
    main()
