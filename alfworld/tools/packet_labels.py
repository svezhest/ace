import json, sys, re, collections
rows = [json.loads(l) for l in open(sys.argv[1])]
c = collections.Counter()
for r in rows:
    u = [m for m in r["prompt"] if m["role"] == "user"][0]["content"]
    u = u[u.find("## Failure Traces"):]
    for m in re.finditer(r"^([A-Z_]+):", u, re.M):
        c[m.group(1)] += 1
    c["traces"] += u.count("## Trace case")
print(c)
