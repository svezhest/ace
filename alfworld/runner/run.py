"""Run the harness in <view>/src on ALFWorld games and write <view>/logs.

Everything here is outside src/: model transport, budget, logging, results. A full copy of the run
(src snapshot, logs, private per-run meta, worker env) goes to runs/<tag>/ (or --out); <view>/logs is then
replaced by this run's logs, so the logs always come from the code currently in <view>/src.

  python run.py --view ../view --split train --n 8 --seed 1 --workers 4 --tag smoke1
  python run.py --view ../view --fake '["@first"]' --n 2 --tag fake   # stub model, no LLM
"""
import argparse
import concurrent.futures as cf
import hashlib
import json
import multiprocessing as mp
import os
import random
import shutil
import sys
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT.parent))   # stand.py — профиль стенда
import stand as STAND                  # noqa: E402
DATA = Path(os.environ.get("ALFWORLD_DATA") or ROOT / "data" / "alfworld")   # game files of the splits
def src_hash(src):
    h = hashlib.sha256()
    for p in sorted(Path(src).glob("*")):
        if p.is_file():
            h.update(p.name.encode() + b"\0" + p.read_bytes() + b"\0")
    return h.hexdigest()[:16]


def expert_hint(game_file, level):
    """Benchmark feedback for results.jsonl beyond ok/reason (ablation axis; 0 = none).
    1: how many steps an expert planner needs from the start (difficulty, no solution).
    2: the expert plan itself (reference solution)."""
    import textworld
    from alfworld.agents.environment.alfred_tw_env import AlfredDemangler, AlfredInfos
    env = textworld.start(str(DATA / game_file), request_infos=textworld.EnvInfos(policy_commands=True),
                          wrappers=[AlfredDemangler(shuffle=False), AlfredInfos])
    plan = list(env.reset()["policy_commands"] or [])
    env.close()
    if level == 1:
        return f"an expert solves this task in {len(plan)} steps"
    return "expert plan: " + "; ".join(plan)


def play(job):
    sys.dont_write_bytecode = True
    sys.path[:0] = [job["src"], str(HERE), str(ROOT / "bench")]
    import bridge
    import fixture
    import harness
    from events import Recorder, events, honest
    from fake import Fake
    from llm import Client, EpisodeEnd

    t0, reason, detail, messages = time.time(), None, "", None
    rec = Recorder(fixture.Episode(job["game"], str(DATA)))
    ep = bridge.Episode(rec)
    if job["fake"] is not None:
        llm = Fake(job["fake"])
    else:
        g = job["gen"]
        llm = Client(g["url"], g["model"], job["wall_limit"], max_tokens=g["max_tokens"], temperature=g["temperature"])
    try:
        messages = harness.run(ep, bridge.guard(ep, llm))
    except bridge.Loop:
        pass
    except EpisodeEnd as e:
        reason, detail = e.reason, e.detail
    except Exception:
        reason, detail = "harness error", traceback.format_exc(limit=5)
    if not isinstance(messages, list):
        messages = llm.conversation or []
    is_honest = honest(rec.sent(), llm.outputs)
    won = rec.bench.won()
    if not is_honest:
        reason, detail = "harness error", "a message handed to the task is not a model reply"
    elif won:
        reason = "success"
    elif reason is None:
        if ep.end is None:
            reason = "harness stopped early"
        elif ep.end.get("detail") in ("repeated action", "repeated reply"):
            reason = ep.end["detail"]
        elif ep.end["reason"] == "step limit":
            reason = "step limit"  # the task's turn limit, or the game's own limit of actions
        else:
            reason = ep.end["reason"]
    rec.bench.close()
    hint = expert_hint(job["game"], job["hint_level"]) if job["hint_level"] > 0 else None
    as_json = [json.dumps(m, sort_keys=True) for m in messages]
    append_only = all([json.dumps(m, sort_keys=True) for m in r] == as_json[:len(r)] for r in llm.requests)
    prompt_tokens = [c["prompt_tokens"] or 0 for c in llm.calls]
    ok = reason == "success"
    return {"run": job["run"], "ok": ok, "reason": reason, "hint": hint,
            "events": events(messages, rec, ep.end, job["src"]),
            "meta": {"run": job["run"], "game": job["game"], "ok": ok, "reason": reason,
                     "detail": detail, "end": ep.end, "honest": is_honest, "sec": round(time.time() - t0, 1),
                     "model_calls": len(llm.calls), "turns": ep.turns, "env_steps": rec.env_steps(),
                     "max_prompt_tokens": max(prompt_tokens, default=0),
                     "completion_tokens": sum(c["completion_tokens"] or 0 for c in llm.calls),
                     "append_only": append_only, "calls": llm.calls}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--view", default=str(ROOT / "view_v3"))
    ap.add_argument("--split", default="train", choices=["train", "val", "test"])
    ap.add_argument("--allow-test", action="store_true", help="test split is for the final measurement only")
    ap.add_argument("--n", type=int, default=8)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--games", nargs="*", help="explicit game files (relative to data root)")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--hint-level", type=int, default=0, help="0: ok/reason only; 1: + expert steps; 2: + plan")
    ap.add_argument("--stand", default="default", help="profile in stands/: model, gateway, generation parameters")
    ap.add_argument("--wall-limit", type=int, default=3600, help="seconds per episode")
    ap.add_argument("--fake", help="JSON script for the stub model (no LLM calls)")
    ap.add_argument("--tag", required=True)
    ap.add_argument("--no-publish", action="store_true", help="do not replace <view>/logs")
    ap.add_argument("--out", help="directory of the run (default: runs/<tag>)")
    a = ap.parse_args()

    if a.split == "test" and not a.allow_test:
        sys.exit("test split is reserved for the final measurement (use --allow-test)")
    view, out = Path(a.view).resolve(), Path(a.out).resolve() if a.out else ROOT / "runs" / a.tag
    if out.exists():
        sys.exit(f"{out} exists")
    src = view / "src"
    splits = json.loads((ROOT / "splits.json").read_text())
    games = a.games or random.Random(a.seed).sample(splits[a.split], a.n)
    P = STAND.load(a.stand)
    gp = STAND.gen(P, "executor", "alfworld")
    stand = {"stand": STAND.meta(P, STAND.check(P, ["executor"]) if a.fake is None else None), "gen": gp}

    out.mkdir(parents=True)
    shutil.copytree(src, out / "src", ignore=shutil.ignore_patterns("__pycache__"))
    (out / "logs").mkdir()
    info = {"tag": a.tag, "src_hash": src_hash(out / "src"), "split": a.split, "seed": a.seed, "n": len(games),
            "hint_level": a.hint_level, "fake": a.fake, "started": time.strftime("%Y-%m-%d %H:%M:%S"),
            "workers": a.workers, **stand}
    (out / "run.json").write_text(json.dumps(info, indent=1))
    print(json.dumps(info), flush=True)

    jobs = [{"run": i + 1, "game": g, "src": str(out / "src"), "fake": json.loads(a.fake) if a.fake else None,
             "gen": gp, "hint_level": a.hint_level, "wall_limit": a.wall_limit}
            for i, g in enumerate(games)]
    results, t0 = [], time.time()
    with cf.ProcessPoolExecutor(a.workers, mp_context=mp.get_context("spawn"), max_tasks_per_child=1) as pool:
        futs = {pool.submit(play, j): j for j in jobs}
        for f in cf.as_completed(futs):
            try:
                r = f.result()
            except Exception:
                j = futs[f]
                r = {"run": j["run"], "ok": False, "reason": "runner error", "hint": None, "events": [],
                     "meta": {"run": j["run"], "game": j["game"], "detail": traceback.format_exc()}}
            results.append(r)
            with open(out / "logs" / f"run_{r['run']}.jsonl", "w") as fh:
                for e in r["events"]:
                    fh.write(json.dumps(e, ensure_ascii=False) + "\n")
            with open(out / "meta.jsonl", "a") as fh:
                fh.write(json.dumps(r["meta"], ensure_ascii=False) + "\n")
            m = r["meta"]
            print(f"[{time.time() - t0:7.0f}s] run {r['run']:3d} ok={r['ok']!s:5} {r['reason']:<18} "
                  f"calls={m.get('model_calls')} ctx={m.get('max_prompt_tokens')} sec={m.get('sec')}", flush=True)

    results.sort(key=lambda r: r["run"])
    with open(out / "logs" / "results.jsonl", "w") as fh:
        for r in results:
            row = {"run": r["run"], "ok": r["ok"], "reason": r["reason"]}
            if a.hint_level > 0:
                row["hint"] = r["hint"]
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    ok = sum(r["ok"] for r in results)
    summary = {"ok": ok, "n": len(results), "wall_sec": round(time.time() - t0, 1)}
    (out / "summary.json").write_text(json.dumps(summary))
    print(json.dumps(summary), flush=True)

    if not a.no_publish:
        if src_hash(src) != info["src_hash"]:
            sys.exit("src/ changed during the run; logs not published to the view")
        logs = view / "logs"
        shutil.rmtree(logs, ignore_errors=True)
        shutil.copytree(out / "logs", logs)


if __name__ == "__main__":
    main()
