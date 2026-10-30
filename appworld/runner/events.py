"""Event log of one episode (logs/run_N.jsonl), from the conversation and the record of the bridge's calls.

Events ("event"): bridge — fill (the values put into the prompt's slots) / execute (code run by the
benchmark's loop, "step" — its number) / end (how the loop ended the episode); prompt — a message the
harness built from src/starting_prompt.md; env — a message with the benchmark's output, as the model
received it; model — the model's reply; harness — other messages of the harness ("from": its file in
src/). The "message" fields in order are the conversation as the model saw it."""
import re
from pathlib import Path

SLOT = re.compile(r"\{\{\s*([\w.]+)\s*\}\}")


def slots_of(template, text):
    """Values of the {{ x }} slots of the template in the filled text -> {name: value}, or None."""
    parts = SLOT.split(template)
    rx = "".join(re.escape(p) if i % 2 == 0 else r"(.*?)" for i, p in enumerate(parts)) + r"\Z"
    m = re.match(rx, text, flags=re.DOTALL)
    if not m:
        return None
    out = {}
    for n, v in zip(parts[1::2], m.groups()):
        out.setdefault(n, v)
    return out


class Recorder:
    """Records the bridge's calls (fill, execute) of one episode, with the number of model calls so far."""

    def __init__(self, episode, llm):
        self.calls = []
        fill, execute = episode.fill, episode.execute

        def rec_fill(text):
            out = fill(text)
            self.calls.append({"call": "fill", "text": text, "out": out})
            return out

        def rec_execute(code):
            out = execute(code)
            self.calls.append({"call": "execute", "code": code, "out": out, "after_model": len(llm.calls)})
            return out
        episode.fill, episode.execute = rec_fill, rec_execute

    def codes(self):
        return [c["code"] for c in self.calls if c["call"] == "execute"]


def honest(codes, outputs):
    """Every code run by the benchmark comes from a model reply (each of its lines is in the reply), in order."""
    i = 0
    for code in codes:
        lines = [x.strip() for x in code.splitlines() if x.strip()]
        while i < len(outputs) and not all(x in (outputs[i].get("content") or "") for x in lines):
            i += 1
        if i == len(outputs):
            return False
        i += 1
    return True


def events(messages, rec, end, src, n_first):
    """n_first: the number of messages in the first request to the model (the prompt, before any reply)."""
    md = {p.read_text(): f"src/{p.name}" for p in sorted(Path(src).glob("*.md"))}
    template = (Path(src) / "starting_prompt.md").read_text()
    fills = [c for c in rec.calls if c["call"] == "fill"]
    filled = " ".join(c["out"] + "\n\n" for c in fills)
    execs = [c for c in rec.calls if c["call"] == "execute"]
    ev, model_n, step, pending = [], 0, 0, None
    for c in fills:
        s = slots_of(c["text"], c["out"]) if c["text"] == template.lstrip() else None
        ev.append({"event": "bridge", "call": "fill", **({"template": "src/starting_prompt.md", "slots": s}
                                                          if s is not None else {"text": c["text"]})})
    for i, m in enumerate(messages):
        c = m.get("content") or ""
        if i < n_first and c and c in filled:
            ev.append({"event": "prompt", "from": "src/starting_prompt.md", "message": m})
        elif m["role"] == "assistant" and i >= n_first:
            model_n += 1
            ev.append({"event": "model", "call": model_n, "message": m})
            while execs and execs[0]["after_model"] == model_n:
                step += 1
                pending = execs.pop(0)
                ev.append({"event": "bridge", "call": "execute", "step": step, "code": pending["code"]})
        elif pending is not None and m["role"] == "user" and (pending["out"] or "") in c:
            ev.append({"event": "env", "message": m})
            pending = None
        elif c in md:
            ev.append({"event": "harness", "from": md[c], "message": m})
        else:
            ev.append({"event": "harness", "message": m})
    ev.append({"event": "bridge", "call": "end", **(end or {"reason": "stopped"})})
    assert [e["message"] for e in ev if "message" in e] == messages
    return ev
