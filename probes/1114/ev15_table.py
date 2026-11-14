"""EV15/EV16: по сессиям писателя с оценщиком — конец, bash к первому вердикту, вердикты по кругам (F — finish, E — конец ходов),
bash после первого Failed и что писатель делал после него.
  python3 probes/1114/ev15_table.py runs/evw_1113 _ev_s1 _nl_s1 ..."""
import glob
import json
import os
import sys

home, tags = sys.argv[1], sys.argv[2:]
for tag in tags:
    for p in sorted(glob.glob(os.path.join(home, "logs", f"*{tag}.jsonl"))):
        bash, first, rs, after, end, failed_at = 0, None, [], {"bash": 0, "edit": 0, "finish": 0}, None, None
        for l in open(p):
            j = json.loads(l)
            if j["type"] == "turn":
                for c in j.get("tool_calls", []):
                    bash += c["name"] == "bash"
                    if failed_at is not None:
                        after[c["name"]] = after.get(c["name"], 0) + 1
            elif j["type"] == "review":
                first = bash if first is None else first
                v = "/".join(f"{x['part'][0]}={x['verdict']}" for x in j["parts"] if x["verdict"] != "skip")
                rs.append(("E" if j.get("at_end") else "F") + f"{j['call']}:{v}")
                if failed_at is None and "Failed" in v or (failed_at is None and "None" in v):
                    failed_at = bash
            elif j["type"] == "end":
                end = j["reason"]
        print(f"{os.path.basename(p)[:-6]:12} bash={bash:3} first_review_at_bash={first} end={end[:38]:38} reviews={rs}"
              + (f" after_first_failed={after}" if failed_at is not None else ""))
