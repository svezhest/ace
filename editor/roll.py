"""10.11: ручной стенд писателя — прокат развилки настоящим харнессом до следующей правки.

История сессии до хода T берётся из её лога, в промпт вносится правка-гипотеза (--sub), и N независимых
продолжений идут настоящими ходами редактора (bash исполняется в свежей копии вида) до первого ответа с edit
или finish. Сама правка не применяется: копия одна на все продолжения, а мерка — что модель решила написать.

  python3 editor/roll.py LOG --turn 5 --n 10 --out OUT.jsonl [--sub OLD NEW]... [--max-turns 12] -- АРГУМЕНТЫ РЕДАКТОРА

АРГУМЕНТЫ РЕДАКТОРА — те же, с какими шла сессия LOG (--home и --tag — новые): из них собираются промпт, копия
вида и песочница. Без --sub системный промпт и первое сообщение обязаны совпасть с логом.
OUT.jsonl: по строке на продолжение — {k, turns: [{content, calls, results}], edit: аргументы первой правки | None}.
"""
import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fork as FK  # noqa: E402
from nrhsi.editor import cfg as C  # noqa: E402
from nrhsi.editor import cli, phase as PH, resume as RS, session as SE, state as R, turn as TU  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("log")
    ap.add_argument("--turn", type=int, required=True)
    ap.add_argument("--n", type=int, default=10)
    ap.add_argument("--max-turns", type=int, default=12)
    ap.add_argument("--sub", nargs=2, action="append", default=[], metavar=("OLD", "NEW"))
    ap.add_argument("--out", required=True)
    cut = sys.argv.index("--")
    a, rest = ap.parse_args(sys.argv[1:cut]), sys.argv[cut + 1:]
    recs = RS.load(a.log)

    def session(role, system, first_user, root, prof, seed, log_path, n_obs=0, resume=None):
        ms0 = FK.history(recs, a.turn)
        assert ms0[0]["content"] == system and ms0[1]["content"] == first_user, "prompt differs from the log"
        for old, new in a.sub:
            assert sum((m.get("content") or "").count(old) for m in ms0[:2]) == 1, f"--sub: {old!r}"
            for m in ms0[:2]:
                m["content"] = m["content"].replace(old, new)
        RS.apply_edits(recs, a.turn, root)
        prev = [r for r in recs if r.get("type") == "turn" and r["i"] < a.turn]
        bash = sum(c["name"] == "bash" and "no longer available" not in str(res.get("shown"))
                   for r in prev for c, res in zip(r["tool_calls"], r["results"]))

        def one(k):
            run = R.Run(role, ms0[0]["content"], ms0[1]["content"], root, prof, seed + 7919 * (k + 1),
                        f"{log_path}.roll{k}", n_obs)
            run.messages = json.loads(json.dumps(ms0))
            run.st["turns"], run.st["bash_calls"] = a.turn - 1, bash
            run.st["tool_calls"] = sum(len(r["tool_calls"]) for r in prev)
            out = {"k": k, "turns": [], "edit": None, "end": None}
            for _ in range(a.max_turns):
                r, dt, end = TU.ask(run)
                if end:
                    out["end"] = end
                    break
                TU.account(run, r, run.est())
                rec, amsg = TU.record(run, r, dt)
                names = [c["function"]["name"] for c in r["calls"]]
                t = {"content": r["content"], "calls": [c["function"] for c in r["calls"]], "results": []}
                out["turns"].append(t)
                if "edit" in names or "finish" in names:
                    c = next(c for c in r["calls"] if c["function"]["name"] in ("edit", "finish"))
                    out["end"] = c["function"]["name"]
                    out["edit"] = c["function"]["arguments"] if out["end"] == "edit" else None
                    break
                end = None if r["calls"] else TU.no_call(run, r, rec)
                TU.run_calls(run, amsg, rec)
                t["results"] = [x["shown"] for x in rec["results"]]
                if end or PH.after_turn(run, False):
                    out["end"] = "session end"
                    break
            run.log.close()
            return out

        with ThreadPoolExecutor(4) as ex:
            outs = list(ex.map(one, range(a.n)))
        with open(a.out, "w") as f:
            for o in outs:
                f.write(json.dumps(o, ensure_ascii=False) + "\n")
        for o in outs:
            print(f"#{o['k']} end={o['end']} turns={len(o['turns'])}", flush=True)
        return "roll", {"model_sec": 0.0, "edits_applied": 0, "edits_attempted": 0, "edit_fail": {}, "max_prompt": 0}, []

    SE.run_session = session
    sys.argv = ["editor"] + rest
    cli.main()


if __name__ == "__main__":
    main()
