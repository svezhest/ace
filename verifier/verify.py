"""R2 — проверка одного report исследователя в чистом контексте той же моделью (CoVe-factored, 2309.11495).

Сессия-проверяльщик получает утверждение (observation) + evidence автора + репозиторий (вид того же набора run,
что у сессии исследователя) и пытается его опровергнуть. Инструменты: bash (песочница и белый список fsr,
политика final: python3, runs), verdict(verdict, why, evidence). Лимит bash — 10 вызовов, потом только verdict.

fsr.py не правится: импортируется как есть, берутся вид/песочница/исполнение bash/вызов модели. Свои отличия —
fsr.HERE (виды и профили песочницы — в verifier/views) и своя петля сессии ниже.

python3 verify.py dry --id R01            промпт и первая реплика
python3 verify.py run --ids R01,R02       сессии (≤ --par своих одновременно, ≤ --total вместе с fsr.py на стенде)
python3 verify.py table                   сводка по results.jsonl + set.tsv
"""
import argparse
import csv
import hashlib
import json
import os
import subprocess
import sys
import threading
import time
import traceback

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCHER = os.path.expanduser("~/Projects/nrhsi/researcher")
sys.path.insert(0, RESEARCHER)
sys.path.insert(0, HERE)
import fsr                      # noqa: E402
from reports_dump import reports  # noqa: E402

VIEWS = {"app": os.path.expanduser("~/Projects/nrhsi/appworld/view"),
         "alf": os.path.expanduser("~/Projects/nrhsi/alfworld/view")}
SET = f"{HERE}/set.tsv"
RESULTS = f"{HERE}/results.jsonl"
BASH_LIMIT = 10
FINAL_TURNS = 3          # ходов только с verdict после лимита
HARD_AT = 52000          # оценка prompt -> только verdict
MAX_NOCALL = 4
TEMP = 0.6
SEED = 1

SYSTEM_T = """The working directory is a read-only copy of a repository: the source code of an AI agent's harness (its prompts and the code that runs it) and the logs of the agent's runs on tasks. Some runs passed and some failed. README.md describes the layout.

Goal: decide whether one claim about this repository is true by checking it against the files. The claim comes with the evidence its author cited; the author had read only part of the files and may be wrong. Try to refute the claim:
- check each statement about the code or the prompts against the code and the prompts themselves;
- check each statement about what happened in a run against that run's log;
- if the claim names a cause of failure, check whether the same thing also happens in passed runs: they are in logs/ next to the failed ones, for comparison;
- look for lines that contradict the claim, not only for lines that agree with it.
The claim is supported if its main statement survives these checks, refuted if the files contradict its main statement, and unclear if what could be read does not decide it.

# Tools
- bash(command): a read-only shell in the working directory. Programs: PROGRAMS. Pipes, ';', '&&', '||', $(...), for/while loops and if work. Nothing can be written (no files, no /tmp). Output longer than OUT_CHARS characters is truncated, so read big files in parts (sed -n '40,90p' FILE, head, tail), search with grep -n, and read the logs with runs.
RUNS_LINE
BSD_LINE
PYTHON_LINE
- verdict(verdict, why, evidence): the result. verdict is "supported", "refuted" or "unclear"; why says what was checked and what was found; evidence lists the lines that decide it ("path:line", "path:start-end", or a short quote with its path).

bash can be called BASH_LIMIT times; after that only verdict remains. Call verdict once, when the check is done."""

FIRST_T = """Claim (KIND):
OBS

Evidence cited by its author:
EV

Check the claim against the files and give the verdict."""

FINAL_MSG = "All BASH_LIMIT bash calls are used; bash is no longer available. Give the verdict now with verdict."
CTX_FINAL_MSG = "The context is nearly full; bash is no longer available. Give the verdict now with verdict."

TOOLS = [
    {"type": "function", "function": {
        "name": "bash", "description": "Run a read-only shell command in the working directory. Pipes, ';', '&&', "
        "'||', $(...), for/while loops and if work; nothing can be written. Long output is truncated: use grep -n, "
        "sed -n 'a,bp', head, tail, runs.",
        "parameters": {"type": "object", "properties": {"command": {"type": "string", "description": "The command line"}},
                       "required": ["command"]}}},
    {"type": "function", "function": {
        "name": "verdict", "description": "The result of the check. Call it once, at the end.",
        "parameters": {"type": "object", "properties": {
            "verdict": {"type": "string", "enum": ["supported", "refuted", "unclear"]},
            "why": {"type": "string", "description": "What was checked and what was found"},
            "evidence": {"type": "array", "items": {"type": "string"},
                         "description": "The lines that decide it: 'path:line', 'path:start-end' or a short quote with its path"}},
            "required": ["verdict", "why", "evidence"]}}},
]
FINAL_TOOLS = [TOOLS[1]]

_setup_lock = threading.Lock()   # fsr.LAYOUT — глобальная: вид строится под замком
_res_lock = threading.Lock()


def init_fsr():
    """Политика final fsr (python3, runs в bash); виды и профили — в verifier/views."""
    fsr.apply_policy("final")
    fsr.HERE = HERE
    assert "python3" in fsr.ALLOWED and "runs" in fsr.ALLOWED and fsr.RUNS_MODE == "bash"


def build_system():
    progs = sorted(fsr.ALLOWED)
    return (SYSTEM_T.replace("PROGRAMS", ", ".join(progs)).replace("OUT_CHARS", str(fsr.OUT_CHARS))
            .replace("RUNS_LINE", fsr.RUNS_LINE).replace("BSD_LINE", fsr.BSD_LINE)
            .replace("PYTHON_LINE", fsr.PYTHON_LINE).replace("BASH_LIMIT", str(BASH_LIMIT)))


def load_set():
    with open(SET) as f:
        return {r["id"]: r for r in csv.DictReader(f, delimiter="\t")}


def claim_of(row):
    """-> (meta сессии исследователя, report args)."""
    meta, rs = reports(row["tag"])
    x = dict(rs)[int(row["n"])]
    return meta, x


def first_user(x):
    ev = x.get("evidence")
    ev = [ev] if isinstance(ev, str) else (ev or [])
    return (FIRST_T.replace("KIND", str(x.get("kind"))).replace("OBS", str(x.get("observation")).strip())
            .replace("EV", "\n".join(f"- {e}" for e in ev) or "(none)"))


def fsr_sha():
    return hashlib.sha256(open(f"{RESEARCHER}/fsr.py", "rb").read()).hexdigest()[:16]


def session(rid, row, system):
    meta_r, x = claim_of(row)
    tids = meta_r["runs"]
    with _setup_lock:
        fsr.LAYOUT = os.path.realpath(VIEWS[row["bench"]])
        vname, lock = fsr.claim_view(f"v_{rid}")
        root = fsr.build_view(vname, tids)
        prof = fsr.sandbox_profile(root)
    os.makedirs(f"{HERE}/logs", exist_ok=True)
    logp = f"{HERE}/logs/{rid}.jsonl"
    log = open(logp, "w", encoding="utf-8", errors="backslashreplace")

    def w(rec):
        log.write(json.dumps(rec, ensure_ascii=False) + "\n")
        log.flush()

    user0 = first_user(x)
    st = {"turns": 0, "bash_calls": 0, "denied": 0, "repeats": 0, "no_call": 0, "bad_call": 0, "max_prompt": 0,
          "gen_tokens": 0, "model_sec": 0.0, "final_turns": 0, "length_stops": 0}
    result, end = None, None
    w({"type": "meta", "id": rid, "source": {"tag": row["tag"], "n": int(row["n"]), "log": meta_r.get("view"),
       "runs": tids}, "bench": row["bench"], "layout": fsr.LAYOUT, "view": vname, "fsr_sha": fsr_sha(),
       "system": system, "first_user": user0, "temperature": TEMP, "seed": SEED, "model": fsr.MODEL,
       "limits": {"bash_limit": BASH_LIMIT, "final_turns": FINAL_TURNS, "hard_at": HARD_AT, "out_chars": fsr.OUT_CHARS,
                  "allowed": sorted(fsr.ALLOWED), "runs_format": fsr.RUNS_FORMAT, "max_gen": fsr.MAX_GEN},
       "start": time.strftime("%H:%M:%S")})
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user0}]
    seen = {}
    final_left = 0
    last_prompt, pending = 0, 0
    try:
        while end is None:
            est = last_prompt + pending
            if est >= fsr.CTX - fsr.MAX_GEN - 1500:
                end = "forced: context too large"
                break
            if not final_left and est >= HARD_AT:
                final_left = FINAL_TURNS
                messages.append({"role": "user", "content": CTX_FINAL_MSG})
            t0 = time.time()
            resp, err = fsr.chat(messages, TEMP, SEED + st["turns"], FINAL_TOOLS if final_left else TOOLS)
            r, perr = (None, err) if err else fsr.parse_response(resp)
            dt = time.time() - t0
            st["model_sec"] += dt
            st["turns"] += 1
            st["final_turns"] += bool(final_left)
            if not r:
                w({"type": "turn", "i": st["turns"], "sec": round(dt, 1), "error": perr})
                end = f"forced: model call failed: {str(perr)[:200]}"
                break
            u = r["usage"]
            last_prompt, pending = (u.get("prompt_tokens") or est) + (u.get("completion_tokens") or 0), 0
            st["max_prompt"] = max(st["max_prompt"], u.get("prompt_tokens") or 0)
            st["gen_tokens"] += u.get("completion_tokens") or 0
            st["length_stops"] += r["finish_reason"] == "length"
            calls = r["calls"]
            rec = {"type": "turn", "i": st["turns"], "sec": round(dt, 1), "usage": u, "final": bool(final_left),
                   "finish_reason": r["finish_reason"], "content": r["content"],
                   "tool_calls": [{"name": c["function"]["name"], "arguments": c["function"]["arguments"]} for c in calls],
                   "results": []}
            amsg = {"role": "assistant", "content": r["content"] or ""}
            if calls:
                amsg["tool_calls"] = [{"id": c["id"] or f"call_{st['turns']}_{j}", "type": "function",
                                       "function": c["function"]} for j, c in enumerate(calls)]
            messages.append(amsg)
            for c in amsg.get("tool_calls", []):
                name, raw = c["function"]["name"], c["function"]["arguments"]
                res = {"name": name}
                try:
                    args = json.loads(raw) if raw else {}
                    if not isinstance(args, dict):
                        raise ValueError("arguments must be a JSON object")
                except Exception as e:  # noqa: BLE001
                    st["bad_call"] += 1
                    out = f"Error: could not parse the arguments as JSON ({e}). Call the tool again with valid JSON."
                    args = None
                if args is None:
                    pass
                elif name == "bash":
                    cmd = args.get("command")
                    if final_left:
                        st["bad_call"] += 1
                        out = "Error: bash is no longer available. Give the verdict with verdict."
                    elif st["bash_calls"] >= BASH_LIMIT:
                        out = f"Error: all {BASH_LIMIT} bash calls are used; this command was not run."
                    elif not isinstance(cmd, str) or not cmd.strip():
                        st["bash_calls"] += 1
                        st["bad_call"] += 1
                        out = "Error: bash needs a 'command' string."
                    else:
                        st["bash_calls"] += 1
                        key = " ".join(cmd.split())
                        if key in seen:
                            st["repeats"] += 1
                            res["repeat"] = True
                            out = (f"This is the same command as bash call {seen[key]}; its output is above. "
                                   "Run a different command, or give the verdict.")
                        else:
                            seen[key] = st["bash_calls"]
                            ok, out, full, info, tr = fsr.bash_output(cmd, root, prof)
                            st["denied"] += not ok
                            res.update(command=cmd, ok=ok, full_chars=len(full), truncated=tr)
                    res["bash_n"] = st["bash_calls"]
                elif name == "verdict":
                    v, why, ev = args.get("verdict"), args.get("why"), args.get("evidence")
                    ev = [ev] if isinstance(ev, str) else ev
                    errs = []
                    if v not in ("supported", "refuted", "unclear"):
                        errs.append("verdict must be supported, refuted or unclear")
                    if not isinstance(why, str) or not why.strip():
                        errs.append("why must be a non-empty string")
                    if not isinstance(ev, list):
                        errs.append("evidence must be a list of strings")
                    if errs:
                        st["bad_call"] += 1
                        out = "Error: verdict not recorded.\n- " + "\n- ".join(errs)
                    else:
                        result = {"verdict": v, "why": why, "evidence": [str(e) for e in ev]}
                        out = "Recorded."
                        end = "verdict"
                else:
                    st["bad_call"] += 1
                    out = f"Error: unknown tool '{name}'. Tools: " + ("verdict." if final_left else "bash, verdict.")
                res["shown"] = out[:6000]
                rec["results"].append(res)
                messages.append({"role": "tool", "tool_call_id": c["id"], "content": out})
                pending += fsr.est_tokens(out) + 10
                if end:
                    break
            if not calls:
                st["no_call"] += 1
                note = ("Your reply contained no tool call. Give the verdict with verdict." if final_left else
                        "Your reply contained no tool call. Continue with bash, or give the verdict with verdict.")
                messages.append({"role": "user", "content": note})
                pending += fsr.est_tokens(note)
                rec["format_fail"] = "none"
                if st["no_call"] >= MAX_NOCALL:
                    end = "forced: replies without a tool call"
            w(rec)
            if end:
                break
            if final_left:
                final_left -= 1
                if not final_left:
                    end = "forced: final turns used, no verdict"
            elif st["bash_calls"] >= BASH_LIMIT:
                final_left = FINAL_TURNS
                note = FINAL_MSG.replace("BASH_LIMIT", str(BASH_LIMIT))
                messages.append({"role": "user", "content": note})
                pending += fsr.est_tokens(note)
                w({"type": "note", "text": note})
    except BaseException as e:  # noqa: BLE001
        end = f"forced: harness error: {type(e).__name__}: {e}"[:300]
        w({"type": "error", "traceback": traceback.format_exc()[-3000:]})
        if not isinstance(e, Exception):
            raise
    finally:
        st["model_sec"] = round(st["model_sec"], 1)
        w({"type": "end", "reason": end, "result": result, "stats": st, "end": time.strftime("%H:%M:%S")})
        log.close()
        fsr.release_view(lock)
    out = {"id": rid, "verdict": (result or {}).get("verdict", "none"), "end": end, **st,
           "why": (result or {}).get("why"), "evidence": (result or {}).get("evidence"), "log": logp}
    with _res_lock, open(RESULTS, "a") as f:
        f.write(json.dumps(out, ensure_ascii=False) + "\n")
    print(json.dumps({k: out[k] for k in ("id", "verdict", "end", "turns", "bash_calls", "max_prompt", "model_sec")}),
          flush=True)
    return out


def stand_sessions():
    """Сессии fsr.py на стенде (процессы python с fsr.py --view; обёртки оболочки не в счёт)."""
    p = subprocess.run(["ps", "-ax", "-o", "command="], capture_output=True, text=True)
    n = 0
    for line in p.stdout.splitlines():
        exe = os.path.basename(line.split(" ", 1)[0]).lower()
        if exe.startswith("python") and " fsr.py --view" in line:
            n += 1
    return n


def run(ids, par, total):
    init_fsr()
    rows = load_set()
    system = build_system()
    queue = list(ids)
    live = []
    waited = False
    while queue or live:
        live = [t for t in live if t.is_alive()]
        if queue and len(live) < par and stand_sessions() + len(live) < total:
            rid = queue.pop(0)
            t = threading.Thread(target=session, args=(rid, rows[rid], system), daemon=False)
            t.start()
            live.append(t)
            print(f"{time.strftime('%H:%M:%S')} start {rid} (stand {stand_sessions()}, mine {len(live)})", flush=True)
            waited = False
            time.sleep(2)
            continue
        if queue and not waited and len(live) < par:
            print(f"{time.strftime('%H:%M:%S')} waiting for a slot (stand {stand_sessions()}, mine {len(live)})",
                  flush=True)
            waited = True
        time.sleep(15)
    print(f"{time.strftime('%H:%M:%S')} all done", flush=True)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("dry")
    d.add_argument("--id", required=True)
    r = sub.add_parser("run")
    r.add_argument("--ids", required=True)
    r.add_argument("--par", type=int, default=2)
    r.add_argument("--total", type=int, default=4)
    a = ap.parse_args()
    if a.cmd == "dry":
        init_fsr()
        row = load_set()[a.id]
        _, x = claim_of(row)
        print(build_system())
        print("-----")
        print(first_user(x))
        print("-----")
        print(json.dumps(TOOLS, indent=1))
    else:
        run([x.strip() for x in a.ids.split(",") if x.strip()], a.par, a.total)


if __name__ == "__main__":
    main()
