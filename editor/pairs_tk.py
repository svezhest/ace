import json, os, sys
H = "/Users/user/Projects/nrhsi/runs/wvar_1104"
V = {"TKS":"xVVxxPxxxP","TKC":"xxVxxPxxxP","TKR":"xxVxxPxxxx","TKF":"xxVxxPxBxB","TKL":"xxVxxPxxxP",
     "TKV":"xxVxxPxxBx","TKVB":"xBBxxxVVxP","TKV_s2":"xxxPxxxxVP","TKV_s3":"BBVxBPxxBP","TKS_s2":"BxBxxPBVxP","TKS_s3":"BBVxBPxxBP",
     "TKW_s1":"xxVxxPxxBx","TKW_s2":"xxVPxxVxVx","TKW_s3":"xBVxBPxxBP","TKP_s1":"xxVxxPxxBx","TKP_s2":"xxxPxxVxxx"}
PAIRS = [("TKC","TKS","покрытие"),("TKR","TKC","return"),("TKF","TKR","проверка первой"),("TKL","TKS","факт в строке"),
         ("TKV","TKL","значения"),("TKVB","TKV","bash 40"),("TKV_s2","TKS_s2","факт+значения"),("TKV_s3","TKS_s3","факт+значения"),
         ("TKW_s1","TKV","почему"),("TKW_s2","TKV_s2","почему"),("TKW_s3","TKV_s3","почему"),
         ("TKP_s1","TKW_s1","задетые"),("TKP_s2","TKW_s2","задетые")]
def load(n):
    f = f"{H}/{n}/logs/wv_{n}.jsonl"
    ev = [json.loads(l) for l in open(f)]
    meta = ev[0]; t = [r for r in ev if r.get("type") == "turn"]
    out = [((r.get("content") or "").strip(), json.dumps([(c["name"], c["arguments"]) for c in r.get("tool_calls") or []])) for r in t]
    import re
    norm = lambda x: re.sub(r"wv_\d\d_[A-Za-z0-9_]+", "SESSION", re.sub(r"[A-Z][a-z]{2} +\d+ \d\d:\d\d", "DATE", x or ""))
    inp = [[norm(x.get("shown")) for x in r.get("results") or []] for r in t]
    return meta, out, inp
rank = {"V":3,"P":2,"B":1,"x":0}
tot = {}
for a, b, what in PAIRS:
    print(f"== {a} против {b} ({what})")
    for i in range(10):
        na, nb = f"{i:02d}_{a}", f"{i:02d}_{b}"
        try: ma, oa, ia = load(na); mb, ob, ib = load(nb)
        except FileNotFoundError: print(f"  {i:02d}: нет лога"); continue
        va, vb = V[a][i], V[b][i]
        if ma.get("system") != mb.get("system") or ma.get("first_user") != mb.get("first_user"):
            cause, at = "старт", 0
        else:
            k = next((j for j, (x, y) in enumerate(zip(oa, ob)) if x != y), None)
            if k is None:
                k = min(len(oa), len(ob))
                cause = "одинаковы" if len(oa) == len(ob) and ia == ib else "вход"
            else:
                cause = "шум"
            j = next((j for j in range(k) if ia[j] != ib[j]), None)
            if j is not None:
                diff = [x for x, y in zip(ia[j], ib[j]) if x != y] or ia[j]
                mech = any(("Check against the observation" in x or "Checks run on src/" in x or "bash calls" in x) for x in diff)
                cause, at = ("механизм" if mech else "посторонн"), j + 1
            else: at = k + 1
        d = "=" if va == vb else ("лучше" if rank[va] > rank[vb] else "хуже")
        if cause in ("механизм",) or (cause=="вход"):
            tot.setdefault(what, []).append((i, d, va, vb))
        mark = "" if cause in ("одинаковы",) else f" ход {at}"
        print(f"  {i:02d}: {cause:9}{mark:8} {vb}→{va} {d}")
print("\nИтог: пары, разошедшиеся из-за механизма (вход отличался до первого разного ответа)")
for w, xs in tot.items():
    c = {k: sum(1 for x in xs if x[1] == k) for k in ("лучше","хуже","=")}
    print(f"  {w:16} пар {len(xs):2}: лучше {c['лучше']}, хуже {c['хуже']}, тот же вердикт {c['=']}  " + " ".join(f"{i:02d}:{vb}→{va}" for i,d,va,vb in xs if d!="="))
