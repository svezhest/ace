"""EV35 (19.11): пул правок 9B + отбор оценщиком, без GPU. На каждый вход есть 4 сессии писателя 9B (EV27 c9n/c9t, EV31
h9n/h9t), их итоговые src размечены (Ok / спорно / F). Оценщик (Haiku 5.5, как в сессии писателя: обе части — логика
`runs_v2` и промпт `prompt_edit`, сборка как nrhsi-wc review.py) судит каждый итог; отбор = итог с Ok оценщика.
  python3 probes/1119/ev35.py [потоков]   → runs/evw_1113/ev35_haiku.jsonl (снятые теги пропускает)"""
import json, os, re, subprocess, sys, tempfile, time
from concurrent.futures import ThreadPoolExecutor
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "probes", "1112"))
import ev_input as EI  # noqa: E402
import ev_judge as EJ  # noqa: E402

VIEW = {"00": "alf_n4", "01": "app_r1", "03": "app_r1", "04": "app_r4", "05": "app_r4", "06": "alf_r1", "07": "alf_r4chk", "09": "app_n2", "14": "app_n2", "t4": "app_r1"}
INP = {"00": "00_v_rr", "01": "01_v_rr", "03": "03_v_rr", "04": "04_v_rr", "05": "05_v_rr", "06": "06_v_rr", "07": "07_v_rr", "09": "09_v_rr", "14": "14_real", "t4": "t4"}
H, T, FULL = (os.path.join(ROOT, "runs", d) for d in ("evw_1113", "typed_1111", "full_1112"))
OUT = os.path.join(H, "ev35_haiku.jsonl")
CWD = tempfile.mkdtemp(prefix="ev35_")
TAGS = [f"{k}_{a}_s1" for k in VIEW for a in ("c9n", "c9t", "h9n", "h9t")]


def haiku(system, user):
    for _ in range(3):
        p = subprocess.run(["claude", "-p", "--safe-mode", "--setting-sources", "", "--model", "haiku", "--effort", "high",
                            "--tools", "", "--system-prompt", system, "--output-format", "json",
                            "--no-session-persistence", "--strict-mcp-config"],
                           input=user, capture_output=True, text=True, cwd=CWD, timeout=1800)
        try:
            d = json.loads(p.stdout)
        except ValueError:
            d = {"is_error": True, "result": (p.stdout + p.stderr)[-500:]}
        if not d.get("is_error"):
            return d
        time.sleep(60)
    return d


def one(tag):
    k = tag.split("_")[0]
    bench = "alf" if VIEW[k].startswith("alf") else "app"
    obs = re.sub(r"^Observation from a study of the agent's failed runs[^\n]*\n+", "", open(os.path.join(T, "in", INP[k] + ".txt")).read())
    final = EI.ES.read_src(os.path.join(H, "work", tag, "src"))
    full = os.path.join(FULL, VIEW[k])
    rec = {"tag": tag, "parts": []}
    try:
        parts = [("code", EI.build_from([(0, final)], full, bench, obs, os.path.join(H, "chk", VIEW[k]), "ev35_" + tag, blocks=True,
                                        logic_only=True, win=(6, 0), sparse=((15, 10), (10, 5), (7, 3)), v2=True), "runs_v2"),
                 ("prompt", EI.build_prompt_from(final, full, bench, obs), "prompt_edit")]
    except subprocess.TimeoutExpired:
        rec["parts"].append({"part": "replay", "verdict": "Failed", "content": "replay timeout"})
        rec["verdict"] = "Failed"
        return rec
    for name, user, prompt in parts:
        if not user:
            rec["parts"].append({"part": name, "verdict": "skip"})
            continue
        t0 = time.time()
        d = haiku(EI.PROMPTS[prompt], user)
        c = d.get("result") or ""
        rec["parts"].append({"part": name, "verdict": None if d.get("is_error") else EJ.parse(c)[0], "content": c,
                             "chars_in": len(user), "sec": round(time.time() - t0, 1), "is_error": d.get("is_error")})
    vs = [p["verdict"] for p in rec["parts"] if p["verdict"] != "skip"]
    rec["verdict"] = "Ok" if all(v == "Ok" for v in vs) else ("Failed" if "Failed" in vs else None)
    return rec


if __name__ == "__main__":
    done = {json.loads(l)["tag"] for l in open(OUT)} if os.path.exists(OUT) else set()
    todo = [t for t in TAGS if t not in done]
    with ThreadPoolExecutor(int(sys.argv[1]) if len(sys.argv) > 1 else 3) as ex:
        for r in ex.map(one, todo):
            open(OUT, "a").write(json.dumps(r, ensure_ascii=False) + "\n")
            print(r["tag"], r["verdict"], [(p["part"], p["verdict"]) for p in r["parts"]], flush=True)
