import json, sys
rows = [json.loads(l) for l in open(sys.argv[1])]
print(json.dumps(rows[0]["metadata"], indent=1)[:1500])
