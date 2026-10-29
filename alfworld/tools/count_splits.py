"""Count solvable ALFWorld games per split; check overlap with the Harness-R1 test set."""
import json, os, sys, collections
root = os.path.expanduser(sys.argv[1])  # .../data/alfworld
hr1 = json.load(open(os.path.expanduser(sys.argv[2])))["mixed"]
out = {}
for split in ["train", "valid_seen", "valid_unseen", "valid_train"]:
    base = os.path.join(root, "json_2.1.1", split)
    games, unsolv, missing = [], 0, 0
    for dirpath, dirs, files in os.walk(base):
        if "traj_data.json" not in files:
            continue
        gp = os.path.join(dirpath, "game.tw-pddl")
        if not os.path.exists(gp):
            missing += 1; continue
        g = json.load(open(gp))
        if not g.get("solvable", False):
            unsolv += 1; continue
        games.append(os.path.relpath(gp, root))
    games.sort()
    types = collections.Counter(p.split("/")[2].split("-")[0] for p in games)
    print(split, "solvable", len(games), "unsolvable", unsolv, "missing", missing, dict(types))
    out[split] = games
hr1set = set(hr1)
allg = set(g for v in out.values() for g in v)
print("hr1 test", len(hr1), "unique", len(hr1set), "found among solvable:", len(hr1set & allg))
for s, v in out.items():
    print("  overlap with", s, len(hr1set & set(v)))
g0 = json.load(open(os.path.join(root, out["train"][0])))
print("grammar has 'in/on':", "in/on" in g0["grammar"], "has 'move {o} to':", "move {o} to" in g0["grammar"])
json.dump(out, open(sys.argv[3], "w"), indent=0)
