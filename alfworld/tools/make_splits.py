"""splits.json: test = Harness-R1 test_set (500, as published); train = solvable official train minus test;
val = solvable valid_seen; leftover valid_unseen not in test kept aside (unused)."""
import json, os, sys
root, hr1_path, out = sys.argv[1], sys.argv[2], sys.argv[3]
def solvable(split):
    res = []
    for d, _, files in os.walk(os.path.join(root, "json_2.1.1", split)):
        gp = os.path.join(d, "game.tw-pddl")
        if "traj_data.json" in files and os.path.exists(gp) and json.load(open(gp)).get("solvable"):
            res.append(os.path.relpath(gp, root))
    return sorted(res)
test = json.load(open(hr1_path))["mixed"]
ts = set(test)
train = [g for g in solvable("train") if g not in ts]
val = solvable("valid_seen")
aside = [g for g in solvable("valid_unseen") if g not in ts]
assert not (set(train) & ts) and not (set(val) & ts) and not (set(train) & set(val))
json.dump({"_note": __doc__, "train": train, "val": val, "test": test, "unused_valid_unseen": aside},
          open(out, "w"), indent=0)
print({k: len(v) for k, v in [("train", train), ("val", val), ("test", test), ("unused", aside)]})
