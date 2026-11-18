"""EV29: подача автора (v2, промпт runs_v2) на Haiku 5.5 через `claude -p` (подписка автора) — те же 26 размеченных правок
кода, что EV26/EV28 (входы runs/evw_1113/ev25_in/v2/). Голый вызов: --safe-mode --setting-sources "" (без CLAUDE.md и
настроек), --tools "" (без инструментов), свой системный промпт, --effort high; температуру CLI не задаёт.
  python3 probes/1118/ev29.py [потоков]     → runs/evw_1113/ev29_v2_haiku.jsonl (снятые теги пропускает)"""
import json, os, subprocess, sys, tempfile, time
from concurrent.futures import ThreadPoolExecutor
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "probes", "1112"))
sys.path.insert(0, os.path.join(ROOT, "probes", "1117"))
import ev_input as EI  # noqa: E402
import ev_judge as EJ  # noqa: E402

LABEL = {**{t: "F" for t in "03_bl_o4_s1 03_ck_o4_s1 06_ck_o4_s2 01_nl_s1 00_bl_o4_s1 00_bl_o4_s2 01_bl_o4_s1 01_bl_o4_s2 01_ck_o4_s1".split()},
         **{t: "Ok" for t in ("00_ck_o4_s1 06_nl_s1 06_ev_s1 07_nl_s1 00_cx_o4_s1 01_cx_o4_s1 03_cx_o4_s1 04_bl_o4_s1 04_ck_o4_s1 "
                              "04_cx_o4_s1 06_bl_o4_s1 06_ck_o4_s1 06_cx_o4_s1 07_bl_o4_s1 07_ck_o4_s1 07_cx_o4_s1 09_ck_o4_s1").split()}}
H = os.path.join(ROOT, "runs", "evw_1113")
OUT = os.path.join(H, "ev29_v2_haiku.jsonl")
CWD = tempfile.mkdtemp(prefix="ev29_")   # пустая папка: никакого проектного контекста


def one(tag):
    user = open(os.path.join(H, "ev25_in", "v2", tag + ".txt")).read()
    t0 = time.time()
    p = subprocess.run(["claude", "-p", "--safe-mode", "--setting-sources", "", "--model", "haiku", "--effort", "high",
                        "--tools", "", "--system-prompt", EI.PROMPTS["runs_v2"], "--output-format", "json",
                        "--no-session-persistence", "--strict-mcp-config"],
                       input=user, capture_output=True, text=True, cwd=CWD, timeout=1800)
    try:
        d = json.loads(p.stdout)
    except ValueError:
        d = {"is_error": True, "result": (p.stdout + p.stderr)[-2000:]}
    c = d.get("result") or ""
    v = None if d.get("is_error") else EJ.parse(c)[0]
    return {"tag": tag, "label": LABEL[tag], "verdict": v, "chars_in": len(user), "content": c, "is_error": d.get("is_error"),
            "usage": d.get("usage"), "models": list(d.get("modelUsage") or {}), "sec": round(time.time() - t0, 1)}


if __name__ == "__main__":
    done = {json.loads(l)["tag"] for l in open(OUT)} if os.path.exists(OUT) else set()
    todo = [t for t in LABEL if t not in done]
    with ThreadPoolExecutor(int(sys.argv[1]) if len(sys.argv) > 1 else 3) as ex:
        for r in ex.map(one, todo):
            open(OUT, "a").write(json.dumps(r, ensure_ascii=False) + "\n")
            print(r["tag"], r["label"], r["verdict"], r["sec"], "ERR" if r["is_error"] else "", flush=True)
