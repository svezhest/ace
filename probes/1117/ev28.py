"""EV28: подача автора (v2, runs_v2) на 9B — оценщик с рассуждением (eval9t) и без (eval9), на 26 размеченных правках кода
из EV25/EV26 (входы те же: runs/evw_1113/ev25_in/v2/). Один вызов, T=0.
  python3 probes/1117/ev28.py <stand>     → runs/evw_1113/ev28_v2_<stand>.jsonl"""
import json, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "probes", "1112"))
import ev_input as EI  # noqa: E402
import ev_judge as EJ  # noqa: E402

LABEL = {**{t: "F" for t in "03_bl_o4_s1 03_ck_o4_s1 06_ck_o4_s2 01_nl_s1 00_bl_o4_s1 00_bl_o4_s2 01_bl_o4_s1 01_bl_o4_s2 01_ck_o4_s1".split()},
         **{t: "Ok" for t in ("00_ck_o4_s1 06_nl_s1 06_ev_s1 07_nl_s1 00_cx_o4_s1 01_cx_o4_s1 03_cx_o4_s1 04_bl_o4_s1 04_ck_o4_s1 "
                              "04_cx_o4_s1 06_bl_o4_s1 06_ck_o4_s1 06_cx_o4_s1 07_bl_o4_s1 07_ck_o4_s1 07_cx_o4_s1 09_ck_o4_s1").split()}}
stand = sys.argv[1]
prof = json.load(open(os.path.join(ROOT, "stands", stand + ".json")))
H = os.path.join(ROOT, "runs", "evw_1113")
out = os.path.join(H, f"ev28_v2_{stand}.jsonl")
done = {json.loads(l)["tag"] for l in open(out)} if os.path.exists(out) else set()
for tag, lab in LABEL.items():
    if tag in done:
        continue
    user = open(os.path.join(H, "ev25_in", "v2", tag + ".txt")).read()
    try:
        r = EJ.call(prof, EI.PROMPTS["runs_v2"], user, 1)
    except Exception as e:  # noqa: BLE001
        open(out, "a").write(json.dumps({"tag": tag, "label": lab, "verdict": "error", "error": str(e)}) + "\n")
        print(tag, "error", e, flush=True)
        continue
    m = r["choices"][0]["message"]
    c = m.get("content") or ""
    v = EJ.parse(c)[0]
    open(out, "a").write(json.dumps({"tag": tag, "label": lab, "verdict": v, "chars_in": len(user), "content": c,
                                     "reasoning": m.get("reasoning_content") or m.get("reasoning") or "",
                                     "usage": r.get("usage"), "finish": r["choices"][0].get("finish_reason")}, ensure_ascii=False) + "\n")
    print(tag, lab, v, len(user), r["choices"][0].get("finish_reason"), flush=True)
