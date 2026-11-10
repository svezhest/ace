"""Запрос развилки против запроса харнесса, без модели.

Проигрывает записанную сессию (как editor/replay.py) и на каждом ходу снимает то, что харнесс отправил бы модели:
сообщения, список инструментов, seed. Потом строит то же из лога, как это делает editor/fork.py (history + инструменты
по признаку final + seed = seed сессии + номер хода - 1), и сравнивает побайтно.

  python3 editor/fork_check.py LOG [--roll T1,T2] -- АРГУМЕНТЫ РЕДАКТОРА (--home и --tag — новые)

--roll: ещё и первый запрос продолжения editor/roll.py на ходах T1, T2 (сообщения и инструменты; seed у продолжений
свой по построению) против запроса живой сессии на тех же ходах.

Идентификаторы вызовов здесь у обеих сторон синтетические (call_<ход>_<j>): что шлюз возвращает свои id и как они
попадают в историю живой сессии, этим не проверяется — только воспроизведением хода с моделью.
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fork as FK  # noqa: E402
from nrhsi.editor import cli, schema as SC, turn as TU  # noqa: E402


def main():
    cut = sys.argv.index("--")
    args = sys.argv[cut + 1:]
    roll = [int(t) for t in sys.argv[sys.argv.index("--roll") + 1].split(",")] if "--roll" in sys.argv[:cut] else []
    turns = iter([r for r in map(json.loads, open(sys.argv[1])) if r.get("type") == "turn" and not r.get("replayed")])
    sent = []

    def ask(run):
        st, r = run.st, next(turns, None)
        if r is None or "error" in r:
            st["turns"] += 1
            return None, 0.0, "forced: script end"
        sent.append(json.dumps([run.messages, run.offered(), run.seed + st["turns"]], ensure_ascii=False, sort_keys=True))
        st["turns"] += 1
        st["final_turns"] += bool(run.final_left)
        return ({"calls": [{"id": None, "function": {"name": c["name"], "arguments": c["arguments"]}}
                           for c in r["tool_calls"]],
                 "content": r.get("content"), "reasoning": None, "usage": r.get("usage") or {},
                 "finish_reason": r.get("finish_reason"), "bad": False}, 0.0, None)

    TU.ask = ask
    sys.argv = ["editor"] + args
    cli.main()
    home, tag = args[args.index("--home") + 1], args[args.index("--tag") + 1]
    recs = FK.load(f"{home}/logs/{tag}.jsonl")
    seed0, bad = recs[0]["seed"], []
    logged = [r for r in recs if r.get("type") == "turn"]
    for k, body in enumerate(sent):
        r = logged[k]
        fork = json.dumps([FK.history(recs, r["i"]), SC.TOOLS[1:] if r["final"] else SC.TOOLS, seed0 + r["i"] - 1],
                          ensure_ascii=False, sort_keys=True)
        if fork != body:
            a, b = json.loads(body), json.loads(fork)
            what = [n for n, x, y in zip(("messages", "tools", "seed"), a, b) if x != y]
            at = next((j for j, (x, y) in enumerate(zip(a[0], b[0])) if x != y), None)
            bad.append({"turn": r["i"], "what": what, "n_live": len(a[0]), "n_fork": len(b[0]), "first_msg": at,
                        "live": a[0][at] if at is not None and at < len(a[0]) else None,
                        "fork": b[0][at] if at is not None and at < len(b[0]) else None})
    res = {"log": tag, "turns": len(sent), "differ": len(bad), "first": bad[:1]}
    if roll:                          # первый запрос продолжения roll.py на ходу T против запроса живой сессии на нём
        import subprocess
        rest = [x for i, x in enumerate(args) if x not in ("--home", "--tag") and args[i - 1] not in ("--home", "--tag")]
        res["roll"] = {}
        for t in roll:
            cap = f"{home}/{tag}.roll{t}.json"
            p = subprocess.run([sys.executable, os.path.join(ROOT, "editor", "roll.py"), f"{home}/logs/{tag}.jsonl",
                                "--turn", str(t), "--n", "1", "--out", os.devnull, "--capture", cap, "--", *rest,
                                "--home", f"{home}/roll", "--tag", f"{tag}_t{t}"], capture_output=True, text=True)
            if not os.path.exists(cap):
                res["roll"][t] = "no capture: " + p.stderr[-300:]
                continue
            live, got = json.loads(sent[t - 1])[:2], json.load(open(cap))
            res["roll"][t] = "same" if live == got else {
                "messages": live[0] == got[0], "tools": live[1] == got[1],
                "tools_live": [x["function"]["name"] for x in live[1]], "tools_roll": [x["function"]["name"] for x in got[1]],
                "n_live": len(live[0]), "n_roll": len(got[0])}
    print(json.dumps(res, ensure_ascii=False))


if __name__ == "__main__":
    main()
