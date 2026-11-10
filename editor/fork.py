"""10.11: ручной стенд писателя — развилка записанной сессии на ходу T.

История до хода T берётся из лога сессии, в неё вносится правка-гипотеза, и следующий ход
модели снимается N раз. Инструменты не исполняются: видно только, что модель делает в этом месте. Ответы
кэшируются по содержимому запроса (LOG.fork/<sha>.json), повторный вызов с теми же входами модель не трогает.

  python3 editor/fork.py LOG --turn 17 --n 10                       # как было: разброс хода 17
  python3 editor/fork.py LOG --turn 17 --last FILE                  # ответ последнего инструмента — текст из FILE
  python3 editor/fork.py LOG --turn 17 --sub OLD NEW                # замена во всех сообщениях истории
  python3 editor/fork.py LOG --turn 17 --note "text"                # сообщение user в конец
  python3 editor/fork.py LOG --turn 17 --final                      # ход без bash (хвост сессии)
  python3 editor/fork.py LOG --turn 17 --show                       # напечатать конец истории и выйти

Продолжить развилку настоящим харнессом — editor/roll.py.
"""
import argparse
import hashlib
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from nrhsi.editor import schema as SC  # noqa: E402
from nrhsi.editor.cfg import F  # noqa: E402


def load(path):
    return [json.loads(line) for line in open(path)]


def history(recs, upto):
    """Сообщения сессии до хода upto (без него)."""
    meta = recs[0]
    ms = [{"role": "system", "content": meta["system"]}, {"role": "user", "content": meta["first_user"]}]
    for r in recs[1:]:
        if r.get("type") == "note":
            ms.append({"role": "user", "content": r["text"]})
        elif r.get("type") == "turn":
            if r["i"] >= upto:
                break
            a = {"role": "assistant", "content": r.get("content") or ""}
            if r["tool_calls"]:
                a["tool_calls"] = [{"id": f"call_{r['i']}_{j}", "type": "function",
                                    "function": {"name": c["name"], "arguments": c["arguments"]}}
                                   for j, c in enumerate(r["tool_calls"])]
            ms.append(a)
            for j, res in enumerate(r["results"]):
                ms.append({"role": "tool", "tool_call_id": f"call_{r['i']}_{j}", "content": res["shown"]})
    return ms


def one(ms, tools, seed, cache):
    body = json.dumps([ms, tools, seed, F.STAND, F.TEMP, F.MAX_GEN], sort_keys=True, ensure_ascii=False)
    p = f"{cache}/{hashlib.sha256(body.encode()).hexdigest()[:20]}.json"
    if os.path.exists(p):
        return json.load(open(p)), True
    resp, err = F.chat(ms, F.TEMP, seed, tools)
    r, perr = (None, err) if err else F.parse_response(resp)
    if not r:
        return {"error": err or perr}, False
    out = {"seed": seed, "content": r["content"], "reasoning": r.get("reasoning"), "finish_reason": r["finish_reason"],
           "usage": r["usage"], "calls": [c["function"] for c in r["calls"]]}
    json.dump(out, open(p, "w"), ensure_ascii=False)
    return out, False


def short(s, n):
    s = (s or "").replace("\n", "⏎")
    return s if len(s) <= n else s[:n] + "…"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("log")
    ap.add_argument("--turn", type=int, required=True)
    ap.add_argument("--n", type=int, default=10)
    ap.add_argument("--seed0", type=int, default=5000)
    ap.add_argument("--stand", default="default")
    ap.add_argument("--last", help="файл: им заменяется ответ последнего инструмента")
    ap.add_argument("--sub", nargs=2, action="append", default=[], metavar=("OLD", "NEW"))
    ap.add_argument("--note")
    ap.add_argument("--final", action="store_true")
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--chars", type=int, default=300)
    ap.add_argument("--out", help="jsonl с полными ответами")
    a = ap.parse_args()
    recs = load(a.log)
    ms = history(recs, a.turn)
    if a.last:
        assert ms[-1]["role"] == "tool"
        ms[-1]["content"] = open(a.last).read()
    for old, new in a.sub:
        n = sum((m.get("content") or "").count(old) for m in ms)
        assert n, f"--sub: {old!r} is not in the history"
        for m in ms:
            if m.get("content"):
                m["content"] = m["content"].replace(old, new)
    if a.note:
        ms.append({"role": "user", "content": a.note})
    if a.show:
        for m in ms[-4:]:
            print(f"--- {m['role']}: {m.get('content')}")
            for c in m.get("tool_calls") or []:
                print(f"    > {c['function']['name']} {c['function']['arguments']}")
        return
    tools = SC.TOOLS[1:] if a.final else SC.TOOLS
    F.apply_stand(a.stand)
    cache = a.log + ".fork"
    os.makedirs(cache, exist_ok=True)
    with ThreadPoolExecutor(4) as ex:
        outs = list(ex.map(lambda k: one(ms, tools, a.seed0 + k, cache), range(a.n)))
    for k, (o, hit) in enumerate(outs):
        if "error" in o:
            print(f"#{k} error: {o['error'][:200]}")
            continue
        print(f"#{k}{' (cache)' if hit else ''} {o['finish_reason']} gen={o['usage'].get('completion_tokens')}: {short(o['content'], a.chars)}")
        for c in o["calls"]:
            print(f"    > {c['name']} {short(c['arguments'], a.chars)}")
    if a.out:
        with open(a.out, "w") as f:
            for o, _ in outs:
                f.write(json.dumps(o, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
