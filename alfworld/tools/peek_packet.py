import json, sys
rows = [json.loads(l) for l in open(sys.argv[1])]
r = rows[0]
print(list(r.keys()))
msgs = r.get("messages") or r.get("prompt")
u = [m for m in msgs if m["role"] == "user"][0]["content"]
i = u.find("## Trace case")
print(u[i:i+4000])
