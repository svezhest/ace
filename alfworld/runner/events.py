"""Event log of one episode (logs/run_N.jsonl), from the conversation and the record of the bridge's calls.

Events ("event"): bridge — start / send (a reply handed to the task; "not_shown": the task's messages the
harness did not put into the conversation) / end (how the task ended the episode); prompt — the system
message built from src/starting_prompt.md; env — a message of the task, as the model received it; model —
the model's reply; harness — other messages of the harness ("from": its file in src/). The "message"
fields in order are the conversation as the model saw it."""
import json
from pathlib import Path


def _key(m):
    return json.dumps(m, sort_keys=True, ensure_ascii=False)


class Recorder:
    """Wraps the bench side: records what went through the bridge."""

    def __init__(self, bench):
        self.bench, self.calls = bench, []

    def start(self):
        out = self.bench.start()
        self.calls.append({"call": "start", "messages": out["messages"], "status": out["status"]})
        return out

    def interact(self, reply):
        out = self.bench.interact(reply)
        self.calls.append({"call": "send", "reply": reply, "messages": out["messages"], "status": out["status"]})
        return out

    def end_of(self, status):
        return self.bench.end_of(status)

    def sent(self):
        return [c["reply"] for c in self.calls if c["call"] == "send"]

    def env_steps(self):
        return sum(m["role"] == "tool" for c in self.calls for m in c["messages"])


def honest(sent, outputs):
    """Every reply handed to the task is a model reply, in the model's order."""
    keys, i = [_key(o) for o in outputs], 0
    for s in map(_key, sent):
        while i < len(keys) and keys[i] != s:
            i += 1
        if i == len(keys):
            return False
        i += 1
    return True


def events(messages, rec, end, src):
    md = {p.read_text(): f"src/{p.name}" for p in sorted(Path(src).glob("*.md"))}
    conv = {_key(m) for m in messages}
    calls = list(rec.calls)
    ev, env_keys, model_n, turn = [], set(), 0, 0

    def bridge(c):
        nonlocal turn
        e = {"event": "bridge", "call": c["call"]}
        if c["call"] == "send":
            turn += 1
            e["turn"] = turn
        hidden = [m for m in c["messages"] if _key(m) not in conv]
        if hidden:
            e["not_shown"] = hidden
        env_keys.update(_key(m) for m in c["messages"])
        ev.append(e)

    if calls and calls[0]["call"] == "start":
        bridge(calls.pop(0))
    for m in messages:
        k = _key(m)
        if m["role"] == "assistant":
            model_n += 1
            ev.append({"event": "model", "call": model_n, "message": m})
            if calls and _key(calls[0]["reply"]) == k:
                bridge(calls.pop(0))
        elif m["role"] == "system":
            ev.append({"event": "prompt", "from": "src/starting_prompt.md", "message": m})
        elif k in env_keys:
            ev.append({"event": "env", "message": m})
        elif (m.get("content") or "") in md:
            ev.append({"event": "harness", "from": md[m["content"]], "message": m})
        else:
            ev.append({"event": "harness", "message": m})
    ev.append({"event": "bridge", "call": "end", **(end or {"reason": "stopped"})})
    assert [e["message"] for e in ev if "message" in e] == messages
    return ev
