import json, os, sys
root = sys.argv[1]; rows = [json.loads(l) for l in open(sys.argv[2])]
a = {"solv": [0, 0, 0], "unsolv": [0, 0, 0]}
for r in rows:
    g = json.load(open(os.path.join(root, r["game_file"])))
    k = "solv" if g.get("solvable") else "unsolv"
    a[k][0] += 1; a[k][1] += r["baseline_reward"] >= 1; a[k][2] += r["effective_patched_reward"] >= 1
print("n, baseline ok, patched ok:", a)
