"""Env conformance check: replay the actions of Harness-R1's published no-patch ALFWorld traces
(reproduction/alfworld_e0 failure packets) through our bridge and compare the visible text
(opening message, every observation incl. the action list) with what their agent saw.
No model involved; only the environment and the bridge's formatting/parsing are exercised.

  .venv/bin/python -I tools/replay_hr1.py ref/Harness-R1/reproduction/alfworld_e0/data view/src data/alfworld
"""
import collections
import json
import os
import re
import sys

data_dir, src, root = sys.argv[1:4]
sys.dont_write_bytecode = True
sys.path.insert(0, src)
import bridge  # noqa: E402

MARK = "\n...[middle truncated]...\n"
rows = [json.loads(l) for l in open(os.path.join(data_dir, "engineer_inputs.jsonl"))]
tasks = [json.loads(l) for l in open(os.path.join(data_dir, "tasks.jsonl"))]
by_batch = collections.defaultdict(list)
for t in tasks:
    by_batch[t["batch_tag"]].append(t["game_file"])


def visible_match(ours, theirs):
    theirs = theirs.strip("\n")
    ours_s = ours.strip("\n")
    if MARK in theirs:
        head, tail = theirs.split(MARK, 1)
        # the packet may also cut the end of the tail, so the tail must only occur after the head
        return ours_s.startswith(head) and tail in ours_s[len(head):]
    return ours_s == theirs or ours_s.startswith(theirs)


def parse_trace(text):
    blocks = re.split(r"\n\n(?=(?:USER|ASSISTANT_TOOL|ASSISTANT_TEXT|OBSERVATION):)", text)
    out = []
    for b in blocks:
        m = re.match(r"(USER|ASSISTANT_TOOL|ASSISTANT_TEXT|OBSERVATION):[ \n]?(.*)", b, re.S)
        if m:
            out.append((m.group(1), m.group(2)))
    return out


stats = collections.Counter()
bad = []
for r in rows:
    games = by_batch[r["metadata"]["batch_tag"]]
    u = [m for m in r["prompt"] if m["role"] == "user"][0]["content"]
    for trace in u.split("## Trace case")[1:]:
        blocks = parse_trace(trace[trace.find("USER:"):])
        if not blocks or blocks[0][0] != "USER":
            stats["unparsed"] += 1
            continue
        cands = []
        for g in games:
            ep = bridge.Episode(g, root)
            if visible_match(ep.reset(), blocks[0][1]):
                cands.append(ep)
            else:
                ep.close()
        if len(cands) != 1:
            stats[f"game_candidates_{len(cands)}"] += 1
            for e in cands:
                e.close()
            continue
        ep = cands[0]
        stats["traces"] += 1
        pending = None
        for kind, body in blocks[1:]:
            if kind == "ASSISTANT_TOOL":
                js = body.split(" ", 1)[1] if " " in body else ""
                try:
                    pending = list(json.loads(js).values())[0]
                except Exception:
                    pending = "__unparsed__"
            elif kind == "OBSERVATION":
                if pending in (None, "__unparsed__") or ep.done:
                    stats["obs_skipped"] += 1
                    pending = None
                    continue
                ours = ep.step(ep.match(pending), pending)
                stats["obs_compared"] += 1
                if visible_match(ours, body):
                    stats["obs_equal"] += 1
                else:
                    stats["obs_diff"] += 1
                    bad.append({"action": pending, "ours": ours, "theirs": body})
                pending = None
        ep.close()

print(dict(stats))
json.dump(bad, open(os.environ.get("REPLAY_DIFFS", "/dev/null"), "w"), indent=1)
for b in bad[:5]:
    print(json.dumps(b, indent=1)[:1500])
