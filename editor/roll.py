"""10.11: ручной стенд писателя — прокат развилки настоящим харнессом до следующей правки.

История сессии до хода T берётся из её лога, в промпт вносится правка-гипотеза (--sub), и N независимых
продолжений идут настоящими ходами редактора (bash исполняется в свежей копии вида) до первого ответа с edit
или finish (--stop edit, правка не применяется), до ответа проверки на первую правку (--stop checked) или до конца
сессии (--stop end). У каждого продолжения своя копия вида и свой лог `<home>/logs/<tag>_rK.jsonl` — полный лог сессии.

  python3 editor/roll.py LOG --turn 5 --n 10 --out OUT.jsonl [--sub OLD NEW]... [--max-turns 12] -- АРГУМЕНТЫ РЕДАКТОРА

АРГУМЕНТЫ РЕДАКТОРА — те же, с какими шла сессия LOG (--home и --tag — новые): из них собираются промпт, копия
вида и песочница. Без --sub системный промпт и первое сообщение обязаны совпасть с логом.
OUT.jsonl: по строке на продолжение — {k, log, turns: [{content, calls, results}], edit: аргументы первой правки | None,
checked: ответ проверки на неё}.
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
from nrhsi.editor import cli, phase as PH, session as SE, state as R, turn as TU  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("log")
    ap.add_argument("--turn", type=int, required=True)
    ap.add_argument("--n", type=int, default=10)
    ap.add_argument("--max-turns", type=int, default=12)
    ap.add_argument("--sub", nargs=2, action="append", default=[], metavar=("OLD", "NEW"))
    ap.add_argument("--out", required=True)
    ap.add_argument("--final-turns", type=int, help="ходов без bash после конца бюджета вместо cfg.FINAL_TURNS (с --turn 1)")
    ap.add_argument("--stop", choices=["edit", "checked", "end"], default="edit",
                    help="edit: на первом ответе с edit, правка не применяется; checked: правка применена и проверена; "
                         "end: до конца сессии (не дольше --max-turns)")
    cut = sys.argv.index("--")
    a, rest = ap.parse_args(sys.argv[1:cut]), sys.argv[cut + 1:]
    recs = FK.load(a.log)

    def session(system, first_user, root, prof, seed, log_path):
        ms0 = FK.history(recs, a.turn)
        if a.turn == 1:               # истории нет: промпт — нынешний (его могли поменять коммиты и --final-turns)
            ms0 = [{"role": "system", "content": system}, {"role": "user", "content": first_user}]
        assert ms0[0]["content"] == system and ms0[1]["content"] == first_user, "prompt differs from the log"
        for old, new in a.sub:
            assert sum((m.get("content") or "").count(old) for m in ms0[:2]) == 1, f"--sub: {old!r}"
            for m in ms0[:2]:
                m["content"] = m["content"].replace(old, new)
        prev = [r for r in recs if r.get("type") == "turn" and r["i"] < a.turn]
        bash = sum(c["name"] == "bash" and "no longer available" not in str(res.get("shown"))
                   for r in prev for c, res in zip(r["tool_calls"], r["results"]))

        from nrhsi.editor import work as WK
        tag = os.path.basename(log_path)[:-len(".jsonl")]
        roots = []
        for k in range(a.n):          # своя копия вида на продолжение: правку можно применить и проверить
            rk = WK.build_work(C.BENCH, f"{tag}_r{k}")
            FK.apply_edits(recs, a.turn, rk)
            roots.append((rk, WK.make_profile(rk, f"{tag}_r{k}")))

        def one(k):
            rk, pk = roots[k]
            run = R.Run(ms0[0]["content"], ms0[1]["content"], rk, pk, seed + 7919 * (k + 1),
                        f"{log_path[:-len('.jsonl')]}_r{k}.jsonl")
            run.w(SE.meta(run, ms0[0]["content"], ms0[1]["content"]))
            for r in recs[1:]:        # лог продолжения — полный лог сессии: годится для fork.py, roll.py и replay.py
                if r.get("type") == "turn" and r["i"] >= a.turn:
                    break
                if r.get("type") in ("turn", "note"):
                    run.w(r)
            run.messages = json.loads(json.dumps(ms0))
            run.st["turns"], run.st["bash_calls"] = a.turn - 1, bash
            run.st["tool_calls"] = sum(len(r["tool_calls"]) for r in prev)
            out = {"k": k, "log": run.log.name, "turns": [], "edit": None, "checked": None, "end": None}
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
                hit = "edit" in names or "finish" in names
                if hit and out["edit"] is None and "edit" in names:
                    out["edit"] = next(c for c in r["calls"] if c["function"]["name"] == "edit")["function"]["arguments"]
                if hit and a.stop == "edit":
                    out["end"] = "edit" if "edit" in names else "finish"
                    break
                end = None if r["calls"] else TU.no_call(run, r, rec)
                finished = TU.run_calls(run, amsg, rec)
                if r["calls"]:
                    run.w(rec)
                t["results"] = [x["shown"] for x in rec["results"]]
                if hit and a.stop == "checked":
                    out["end"] = "checked"
                    out["checked"] = t["results"][names.index("edit")] if "edit" in names else None
                    break
                if end or PH.after_turn(run, finished):
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
    if a.final_turns:
        assert a.turn == 1
        C.FINAL_TURNS = a.final_turns
    sys.argv = ["editor"] + rest
    cli.main()


if __name__ == "__main__":
    main()
