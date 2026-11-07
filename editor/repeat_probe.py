"""6.11: проба ответа на повтор команды без целых сессий. Точка — ход сессии писателя (runs/wvar_1104), где bash
получил «This is the same command as tool call N». Контекст из лога до этого хода; ответ на повтор подменяется
вариантом; модель сэмплируется K раз; мерка — есть ли в следующем ходе та же (exact) или почти та же (near) команда.
Варианты: old — как в логе; clean — «already run… tells you nothing new: change the command…» + вывод целиком;
plain — вывод целиком, как в shell; resample — ход перед повтором сэмплируется заново (повтор не исполняется);
cut — обе копии (исходный вызов с выводом и повтор) вырезаны из истории, в конце — заметка харнесса без текста
команды: программы, файлы, что напечатано; para — то же вырезание, а заметка — пересказ отдельного чистого вызова
модели (только команда): её замысел своими словами, вывод — дословно.
Место вставки пересказа (6.11, автор): para_res — вместо ответа на повтор (копий команды 2); para_user — повтор
вырезан, ответ модели прерван, user: <пересказ> (копия 1); para_first — повторы вырезаны, пересказ дописан к ответу
на первый вызов (копия 1, на старом месте); para — все копии вырезаны, заметка в конце (копий 0).
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


def tools_for(s):
    """Схема инструментов сессии по её summary (флаги intent, scratch, finish_review, rerun_tool)."""
    from nrhsi.editor import cfg as EC
    EC.SCRATCH = str(s.get("scratch")) == "True"
    EC.INTENT = str(s.get("intent")) == "True" or str(s.get("intent_opt")) == "True"
    EC.INTENT_OPT = str(s.get("intent_opt")) == "True"
    EC.FINISH_REVIEW = str(s.get("finish_review")) == "True"
    EC.RERUN_TOOL = str(s.get("rerun_tool")) == "True"
    return SC.role_tools("editor")


def summary_of(log):
    f = os.path.join(os.path.dirname(os.path.dirname(log)), "out", os.path.basename(log)[:-6] + ".summary.json")
    return json.load(open(f)) if os.path.exists(f) else None


def points_wide():
    """Точки повтора во всех логах писателя (runs/**/logs), кроме уже взятых points(); схема — по summary сессии."""
    base = {(p["session"], p["turn"], p["j"]) for p in points()}
    seen_ctx, out = set(), []
    for p in sorted(glob.glob(f"{ROOT}/runs/**/logs/*.jsonl", recursive=True)):
        try:
            recs = [json.loads(x) for x in open(p)]
        except Exception:  # noqa: BLE001
            continue
        if not recs or recs[0].get("type") != "meta" or recs[0].get("role") != "editor":
            continue
        s = summary_of(p)
        if s is None or str(s.get("hide_tools")) == "True":
            continue
        name = p.split("/")[-3] if p.startswith(H) else os.path.relpath(p, ROOT)
        turns = [r for r in recs if r.get("type") == "turn" and r.get("i") is not None]
        for t in turns:
            for j, (c, res) in enumerate(zip(t.get("tool_calls") or [], t.get("results") or [])):
                if c["name"] != "bash" or not (res.get("shown") or "").startswith(REP) or (name, t["i"], j) in base:
                    continue
                key = cmd_of(c)
                orig = next(((u["i"], jj, x) for u in turns if u["i"] < t["i"]
                             for jj, (cc, x) in enumerate(zip(u.get("tool_calls") or [], u.get("results") or []))
                             if cc["name"] == "bash" and cmd_of(cc) == key and not (x.get("shown") or "").startswith(REP)), None)
                if orig is None:
                    continue
                h = hashlib.md5(json.dumps(history(recs, t["i"])[:-1], sort_keys=True).encode()).hexdigest()
                if h in seen_ctx:
                    continue
                seen_ctx.add(h)
                ou, oj, orig = orig
                out.append({"session": name, "turn": t["i"], "j": j, "cmd": key, "n": int(res["shown"][len(REP):].split(",")[0]),
                            "orig": orig["shown"], "ou": ou, "oj": oj, "recs": recs, "summary": s, "tools": tools_for(s)})
    return out


def failed(o):
    o = (o or "").strip()
    return (o.startswith("(no output") or "[stderr]" in o or "Traceback" in o or o.startswith("Error:")
            or "did not end within" in o)


def points_firstfail(npos=50, nneg=20):
    """Первый провал команды (ошибка, пусто, таймаут) в сессиях писателя wvar_1104 со схемой по умолчанию.
    pos — следующий bash в ближайших 2 ходах почти тот же (>= 0.9), neg — нет. Выбор детерминирован (md5)."""
    pos, neg, seen_ctx = [], [], set()
    for p in sorted(glob.glob(f"{H}/*/logs/*.jsonl")):
        name = p.split("/")[-3]
        s = summary_of(p)
        if s is None or any(str(s.get(k)) == "True" for k in SIMPLE):
            continue
        recs = [json.loads(x) for x in open(p)]
        turns = [r for r in recs if r.get("type") == "turn" and r.get("i") is not None]
        seen_cmd = set()
        for ti, t in enumerate(turns):
            for j, (c, res) in enumerate(zip(t.get("tool_calls") or [], t.get("results") or [])):
                if c["name"] != "bash":
                    continue
                key = cmd_of(c)
                sh = res.get("shown") or ""
                if not key or key in seen_cmd or sh.startswith(REP) or "no longer available" in sh or not failed(sh):
                    seen_cmd.add(key)
                    continue
                seen_cmd.add(key)
                nxt = [cmd_of(x) for u in turns[ti + 1: ti + 3] for x in u.get("tool_calls") or [] if x["name"] == "bash"]
                if not nxt:
                    continue
                near = any(difflib.SequenceMatcher(None, x, key).ratio() >= 0.9 for x in nxt)
                h = hashlib.md5(json.dumps(history(recs, t["i"]), sort_keys=True).encode()).hexdigest()
                if h in seen_ctx:
                    continue
                seen_ctx.add(h)
                pt = {"session": name, "turn": t["i"], "j": j, "cmd": key, "n": 0, "orig": sh, "ou": t["i"], "oj": j,
                      "recs": recs, "summary": s, "pos": near, "rank": hashlib.md5(f"{name}{t['i']}{j}".encode()).hexdigest()}
                (pos if near else neg).append(pt)
    pos.sort(key=lambda x: x["rank"])
    neg.sort(key=lambda x: x["rank"])
    return pos[:npos] + neg[:nneg]


def abs_now(msgs, p, para):
    """Провалившийся вызов вырезан сразу (вызов и ответ); user: что он пытался сделать и что напечатал."""
    tid = f"call_{p['turn']}_{p['j']}"
    out = []
    for m in msgs:
        if m["role"] == "tool" and m["tool_call_id"] == tid:
            continue
        if m["role"] == "assistant" and any(c["id"] == tid for c in m.get("tool_calls") or []):
            m = dict(m)
            m["tool_calls"] = [c for c in m["tool_calls"] if c["id"] != tid]
            if not m["tool_calls"]:
                del m["tool_calls"]
                if not (m.get("content") or "").strip():
                    continue
        out.append(m)
    o = p["orig"].strip()
    o = o if len(o) <= 400 else o[:400] + " …"
    out.append({"role": "user", "content": f"Your last bash call was taken out of this conversation. What it tried: "
                                           f"{para} It printed:\n{o}"})
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


def cut(msgs, p, whole=False):
    """Вырезать вызовы (ou, oj) и (turn, j) с их выводами; пустой ответ ассистента без вызовов — тоже (whole — и с
    текстом); в конце заметка."""
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
                if whole or not (m.get("content") or "").strip():
                    continue
        out.append(m)
    o = p["orig"].strip()
    o = o if len(o) <= 400 else o[:400] + " …"
    out.append({"role": "user", "content": f"{len(drop)} identical bash calls ({gist(p['cmd'])}) were taken out of this "
                                            f"conversation. Each printed:\n{o}"})
    return out


PARA_SYS = ("You restate what a shell command in a code repository tries to do, for a reader who will not see the "
            "command. Describe its aim in your own words, in one or two sentences. The reader gets its output separately.")


def paraphrase(p, seed):
    msgs = [{"role": "system", "content": PARA_SYS}, {"role": "user", "content": f"Command:\n{p['cmd']}"}]
    resp, err = F.chat(msgs, F.TEMP, seed)
    r, perr = (F.parse_response(resp) if not err else (None, err))
    return ((r or {}).get("content") or "").strip(), err or perr


def leak(text, cmd):
    """Самый длинный общий кусок пересказа и команды (символов)."""
    m = difflib.SequenceMatcher(None, text, cmd, autojunk=False).find_longest_match(0, len(text), 0, len(cmd))
    return m.size


def cut_para(msgs, p, para):
    out = cut(msgs, p)
    k = out[-1]["content"].split(" identical")[0]
    o = p["orig"].strip()
    o = o if len(o) <= 400 else o[:400] + " …"
    out[-1] = {"role": "user", "content": f"{k} identical bash calls were taken out of this conversation. What they "
                                          f"tried: {para} Each printed:\n{o}"}
    return out


def cut_para2(msgs, p, para):
    """para без двух изъянов (7.11): ответ ассистента, у которого не осталось вызовов, вырезан целиком; вывод не обрезан."""
    out = cut(msgs, p, whole=True)
    k = out[-1]["content"].split(" identical")[0]
    out[-1] = {"role": "user", "content": f"{k} identical bash calls were taken out of this conversation. What they "
                                          f"tried: {para} Each printed:\n{p['orig'].strip()}"}
    return out


def _clip(o):
    o = o.strip()
    return o if len(o) <= 400 else o[:400] + " …"


def para_res(msgs, p, para):
    """Ответ на повтор (последний tool) — пересказ и вывод; вызов остаётся."""
    out = [dict(m) for m in msgs]
    tid = f"call_{p['turn']}_{p['j']}"
    t = next(m for m in out if m["role"] == "tool" and m["tool_call_id"] == tid)
    t["content"] = (f"Not run: this is the same command as tool call {p['n']}, and no file has changed since, so it "
                    f"would print the same. What it tries: {para} It printed:\n{_clip(p['orig'])}")
    return out


def para_user(msgs, p, para):
    """Повтор вырезан из ответа модели (его ответ — тоже), дальше user: пересказ; первый вызов остаётся."""
    tid = f"call_{p['turn']}_{p['j']}"
    out = []
    for m in msgs:
        if m["role"] == "tool" and m["tool_call_id"] == tid:
            continue
        if m["role"] == "assistant" and any(c["id"] == tid for c in m.get("tool_calls") or []):
            m = dict(m)
            m["tool_calls"] = [c for c in m["tool_calls"] if c["id"] != tid]
            if not m["tool_calls"]:
                del m["tool_calls"]
                if not (m.get("content") or "").strip():
                    continue
        out.append(m)
    out.append({"role": "user", "content": f"Your last bash call was not run: it is the same command as tool call "
                                           f"{p['n']}, and no file has changed since, so it would print the same. "
                                           f"What it tries: {para} It printed:\n{_clip(p['orig'])}"})
    return out


def para_first(msgs, p, para):
    """Повторы с тем же выводом вырезаны; к ответу на первый вызов дописан пересказ и что повтор не исполнялся."""
    first = f"call_{p['ou']}_{p['oj']}"
    res = {m["tool_call_id"]: m["content"] for m in msgs if m["role"] == "tool"}
    drop = {c["id"] for m in msgs if m["role"] == "assistant" for c in m.get("tool_calls") or []
            if c["id"] != first and c["function"]["name"] == "bash" and cmd_of(c["function"]) == p["cmd"]
            and (res.get(c["id"]) == p["orig"] or (res.get(c["id"]) or "").startswith(REP))}
    out = []
    for m in msgs:
        if m["role"] == "tool" and m["tool_call_id"] in drop:
            continue
        if m["role"] == "tool" and m["tool_call_id"] == first:
            m = dict(m)
            m["content"] = (m["content"].rstrip() + f"\n\n[This command was sent again later and not run: no file "
                            f"had changed, so it would print the same. What it tries: {para}]")
        if m["role"] == "assistant" and m.get("tool_calls"):
            m = dict(m)
            m["tool_calls"] = [c for c in m["tool_calls"] if c["id"] not in drop]
            if not m["tool_calls"]:
                del m["tool_calls"]
                if not (m.get("content") or "").strip():
                    continue
        out.append(m)
    return out


POS = {"para2": cut_para2, "para_res": para_res, "para_user": para_user, "para_first": para_first, "abs_now": abs_now}


def judge(calls, cmd):
    cs = [cmd_of(c["function"]) for c in calls if c["function"]["name"] == "bash"]
    exact = any(c == cmd for c in cs)
    near = exact or any(difflib.SequenceMatcher(None, c, cmd).ratio() >= 0.9 for c in cs)
    return exact, near, cs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--k", type=int, default=3)
    ap.add_argument("--variants", default="old,clean,plain,resample,cut,para")
    ap.add_argument("--stand", default="default")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--pool", default="base", choices=["base", "wide", "firstfail"])
    ap.add_argument("--npos", type=int, default=60)
    ap.add_argument("--nneg", type=int, default=20)
    a = ap.parse_args()
    pts = (points_firstfail(a.npos, a.nneg) if a.pool == "firstfail" else {"base": points, "wide": points_wide}[a.pool]())
    print(json.dumps({"points": len(pts), "sessions": len({p["session"] for p in pts})}), flush=True)
    if a.list:
        for p in pts:
            print(p["session"], p["turn"], p["cmd"][:100])
        return
    F.apply_stand(a.stand)
    tools0 = [SC.BASH_SCHEMA, SC.EDIT_SCHEMA, SC.FINISH_SCHEMA]
    paras = json.load(open(a.out + ".para.json")) if os.path.exists(a.out + ".para.json") else {}
    done = set()
    if os.path.exists(a.out):
        for x in open(a.out):
            r = json.loads(x)
            done.add((r["session"], r["turn"], r["j"], r["variant"], r["sample"]))
    with open(a.out, "a") as f:
        for p in pts:
            for v in a.variants.split(","):
                if v == "resample":
                    msgs = history(p["recs"], p["turn"], cut_assistant=True)
                elif v == "cut":
                    msgs = cut(history(p["recs"], p["turn"]), p)
                elif v == "para" or v in POS:
                    pk = f"{p['session']}|{p['turn']}|{p['j']}"
                    if pk not in paras:
                        txt, perr2 = paraphrase(p, 800_000 + p["turn"])
                        paras[pk] = {"text": txt, "error": perr2, "leak": leak(txt, p["cmd"])}
                        with open(a.out + ".para.json", "w") as g:
                            json.dump(paras, g, ensure_ascii=False, indent=0)
                    if not paras[pk]["text"]:
                        continue
                    h = history(p["recs"], p["turn"])
                    msgs = POS[v](h, p, paras[pk]["text"]) if v in POS else cut_para(h, p, paras[pk]["text"])
                else:
                    msgs = history(p["recs"], p["turn"], sub=variant_sub(p, v))
                for s in range(a.k):
                    if (p["session"], p["turn"], p["j"], v, s) in done:
                        continue
                    seed = 900_000 + 1000 * s + p["turn"]          # сдвиг от seed сессии
                    t0 = time.time()
                    resp, err = F.chat(msgs, F.TEMP, seed, p.get("tools") or tools0)
                    dt = round(time.time() - t0, 1)
                    u = (resp or {}).get("usage") or {}
                    r, perr = (F.parse_response(resp) if not err else (None, err))
                    calls = (r or {}).get("calls") or []
                    ex, nr, cs = judge(calls, p["cmd"])
                    f.write(json.dumps({"session": p["session"], "turn": p["turn"], "j": p["j"], "variant": v,
                                        "sample": s, "cmd": p["cmd"], "exact": ex, "near": nr, "next_bash": cs, "pos": p.get("pos"),
                                        "next_tools": [c["function"]["name"] for c in calls],
                                        "content": ((r or {}).get("content") or "")[:400], "error": err or perr, "sec": dt,
                                        "prompt_tokens": u.get("prompt_tokens"),
                                        "cached": (u.get("prompt_tokens_details") or {}).get("cached_tokens")},
                                       ensure_ascii=False) + "\n")
                    f.flush()


if __name__ == "__main__":
    main()
