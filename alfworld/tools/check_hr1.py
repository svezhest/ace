import json, os, sys, collections
root = sys.argv[1]; hr1 = json.load(open(sys.argv[2]))["mixed"]
c = collections.Counter()
for p in hr1:
    fp = os.path.join(root, p)
    if not os.path.exists(fp): c["missing"] += 1; continue
    g = json.load(open(fp)); c["solvable=%s" % g.get("solvable")] += 1
print(c)
