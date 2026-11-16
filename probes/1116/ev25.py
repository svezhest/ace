"""EV25: подача автора (EV12: v2, runs_v2) против EV6a (blocks, runs) на итоговых src, где EV6a ошибся по логике.
Как EV20 (probes/1114/ev20.py), но в два шага, чтобы входы собрать без модели:
  python3 probes/1116/ev25.py build <var> <tag>...   — собрать вход в runs/evw_1113/ev25_in/<var>/<tag>.txt
  python3 probes/1116/ev25.py call  <var> <tag>...   — один вызов 27B plain27 (T=0) на собранном входе
                                                       → runs/evw_1113/ev25_<var>_plain27.jsonl"""
import json, os, re, sys
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "probes", "1112"))
import ev_input as EI  # noqa: E402

VIEW = {"00": "alf_n4", "01": "app_r1", "03": "app_r1", "04": "app_r4", "06": "alf_r1", "07": "alf_r4chk", "09": "app_n2", "14": "app_n2"}
INP = {"00": "00_v_rr", "01": "01_v_rr", "03": "03_v_rr", "04": "04_v_rr", "06": "06_v_rr", "07": "07_v_rr", "09": "09_v_rr", "14": "14_real"}
H, T, FULL = (os.path.join(ROOT, "runs", d) for d in ("evw_1113", "typed_1111", "full_1112"))
VAR = {"ev6a": dict(blocks=True), "v2": dict(blocks=True, win=(6, 0), sparse=((15, 10), (10, 5), (7, 3)), v2=True)}
PROMPT = {"ev6a": "runs", "v2": "runs_v2"}
mode, var, tags = sys.argv[1], sys.argv[2], sys.argv[3:]
ind = os.path.join(H, "ev25_in", var)
os.makedirs(ind, exist_ok=True)

if mode == "build":
    for tag in tags:
        k = tag.split("_")[0]
        bench = "alf" if VIEW[k].startswith("alf") else "app"
        obs = re.sub(r"^Observation from a study of the agent's failed runs[^\n]*\n+", "",
                     open(os.path.join(T, "in", INP[k] + ".txt")).read())
        final = EI.ES.read_src(os.path.join(H, "work", tag, "src"))
        user = EI.build_from([(0, final)], os.path.join(FULL, VIEW[k]), bench, obs, os.path.join(H, "chk", VIEW[k]), tag,
                             logic_only=True, **VAR[var])
        open(os.path.join(ind, tag + ".txt"), "w").write(user or "")
        print(tag, var, len(user or ""), flush=True)
    sys.exit(0)

import ev_judge as EJ  # noqa: E402
prof = json.load(open(os.path.join(ROOT, "stands", "plain27.json")))
out = os.path.join(H, f"ev25_{var}_plain27.jsonl")
done = {json.loads(l)["tag"] for l in open(out)} if os.path.exists(out) else set()
for tag in tags:
    if tag in done:
        continue
    user = open(os.path.join(ind, tag + ".txt")).read()
    if not user:
        open(out, "a").write(json.dumps({"tag": tag, "verdict": "skip"}) + "\n")
        continue
    try:
        r = EJ.call(prof, EI.PROMPTS[PROMPT[var]], user, 1)
    except Exception as e:  # noqa: BLE001 — ошибка шлюза: записать и идти дальше
        open(out, "a").write(json.dumps({"tag": tag, "verdict": "error", "chars_in": len(user), "error": str(e)}) + "\n")
        print(tag, "error", e, flush=True)
        continue
    c = r["choices"][0]["message"].get("content") or ""
    v = EJ.parse(c)[0]
    open(out, "a").write(json.dumps({"tag": tag, "verdict": v, "chars_in": len(user), "content": c}, ensure_ascii=False) + "\n")
    print(tag, v, len(user), flush=True)
