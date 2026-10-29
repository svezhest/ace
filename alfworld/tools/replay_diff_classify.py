import json, re, sys, collections
MARK = "\n...[middle truncated]...\n"
bad = json.load(open(sys.argv[1])); c = collections.Counter(); rest = []
for b in bad:
    t = b["theirs"]
    t = re.split(r"\n\n(?:Included traces after budget|## |\.\.\.$|Approx input)", t)[0]
    t = t.rstrip("\n.").rstrip()
    o = b["ours"].strip("\n")
    if MARK in t:
        h, tl = t.split(MARK, 1); ok = o.startswith(h) and tl.rstrip(".") in o[len(h):]
    else:
        ok = o.startswith(t)
    c["equal_after_trailer_strip" if ok else "real_diff"] += 1
    if not ok: rest.append(b)
print(dict(c))
for b in rest[:3]:
    print(json.dumps(b)[:1200])
