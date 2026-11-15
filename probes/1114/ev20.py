"""EV20: оценщик логики на итоговых src писателя (EV15/EV16) — подача автора (EV12: v2, runs_v2) против EV6a (blocks, runs).
Вход как в review.py: build_from на итоговом src, полный вид, наблюдение без заголовка; 27B plain27, T=0, один вызов."""
import json, os, re, sys
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "probes", "1112"))
import ev_input as EI  # noqa: E402
import ev_judge as EJ  # noqa: E402

VIEW = {"00": "alf_n4", "01": "app_r1", "03": "app_r1", "04": "app_r4", "06": "alf_r1", "07": "alf_r4chk", "09": "app_n2", "14": "app_n2"}
INP = {"00": "00_v_rr", "01": "01_v_rr", "03": "03_v_rr", "04": "04_v_rr", "06": "06_v_rr", "07": "07_v_rr", "09": "09_v_rr", "14": "14_real"}
H, T, FULL = (os.path.join(ROOT, "runs", d) for d in ("evw_1113", "typed_1111", "full_1112"))
VAR = {"ev6a": dict(blocks=True), "v2": dict(blocks=True, win=(6, 0), sparse=((15, 10), (10, 5), (7, 3)), v2=True)}
PROMPT = {"ev6a": "runs", "v2": "runs_v2"}
prof = json.load(open(os.path.join(ROOT, "stands", "plain27.json")))
var = sys.argv[1]
out = os.path.join(H, f"ev20_{var}_plain27{os.environ.get('EV20_TAG', '')}.jsonl")   # 15.11: EV20_TAG=_q4 — тот же замер на другом стенде
done = {json.loads(l)["tag"] for l in open(out)} if os.path.exists(out) else set()
for tag in sys.argv[2:]:
    if tag in done:
        continue
    k = tag.split("_")[0]
    bench = "alf" if VIEW[k].startswith("alf") else "app"
    obs = re.sub(r"^Observation from a study of the agent's failed runs[^\n]*\n+", "", open(os.path.join(T, "in", INP[k] + ".txt")).read())
    final = EI.ES.read_src(os.path.join(H, "work", tag, "src"))
    user = EI.build_from([(0, final)], os.path.join(FULL, VIEW[k]), bench, obs, os.path.join(H, "chk", VIEW[k]), tag,
                         logic_only=True, **VAR[var])
    if not user:
        open(out, "a").write(json.dumps({"tag": tag, "verdict": "skip"}) + "\n")
        print(tag, "skip", flush=True)
        continue
    try:
        r = EJ.call(prof, EI.PROMPTS[PROMPT[var]], user, 1)
    except Exception as e:  # noqa: BLE001 — 14.11: 500 от шлюза на большом входе; записать и идти дальше
        open(out, "a").write(json.dumps({"tag": tag, "verdict": "error", "chars_in": len(user), "error": str(e)}) + "\n")
        print(tag, "error", len(user), e, flush=True)
        continue
    c = r["choices"][0]["message"].get("content") or ""
    v = EJ.parse(c)[0]
    open(out, "a").write(json.dumps({"tag": tag, "verdict": v, "chars_in": len(user), "content": c}, ensure_ascii=False) + "\n")
    print(tag, v, len(user), flush=True)
