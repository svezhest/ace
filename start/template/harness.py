"""Agent loop.

Builds the conversation from the prompts in src/ and the benchmark's messages from bridge.py, asks the
model for the next step, hands each step to the benchmark and runs the hooks from hooks.py, until the
benchmark ends the episode. A step that a hook sends back is not handed to the benchmark.
"""
import copy
from pathlib import Path

import bridge
import hooks

SRC = Path(__file__).parent


def prompt(name):
    return (SRC / name).read_text()


def user(text):
    return {"role": "user", "content": text}


def call_hook(name, ctx, nb):
    fn = getattr(hooks, name, None)
    if fn is None:
        return None
    try:
        out = fn(copy.deepcopy(ctx), nb)
    except Exception:
        return None
    return out if isinstance(out, dict) else None


def make_ctx(state, episode, history, output=""):
    return {
        "observation": state["observation"],
        "output": output,
        "step": episode.steps,
        "max_step": bridge.STEP_LIMIT,
        "remaining_steps": bridge.STEP_LIMIT - episode.steps,
        "history": copy.deepcopy(history),
    }


def run(episode, llm):
    """Play one episode. `llm(messages)` returns the assistant message. Returns the conversation."""
    nb = {}
    history = {"last_actions": [], "last_observations": []}
    state = {"observation": episode.start()}
    system = prompt("starting_prompt.md")
    out = call_hook("on_init", make_ctx(state, episode, history), nb) or {}
    skills = [s["text"] for s in out.get("skills") or [] if isinstance(s, dict) and s.get("text")]
    if skills:
        system += "\n\nSome tips that may help for this task:\n" + "\n".join(f"- {s}" for s in skills)
    messages = [{"role": "system", "content": system}, user(state["observation"])]

    while not episode.finished:
        out = call_hook("make_pre_hint", make_ctx(state, episode, history), nb)
        if out and out.get("message"):
            messages.append(user(out["message"]))

        reply = llm(messages)
        messages.append(reply)
        action = reply.get("content") or ""

        out = call_hook("on_before_action", make_ctx(state, episode, history, action), nb)
        if out and out.get("kind") == "block_and_prompt":
            messages.append(user(out.get("message") or "Harness blocked this step. Write another step."))
            continue

        obs = episode.send(action)
        messages.append(user(obs))
        state = {"observation": obs}
        history["last_actions"].append(action)
        history["last_observations"].append(obs)

        out = call_hook("on_post_step", make_ctx(state, episode, history, action), nb)
        if out and out.get("kind") == "inject_hint" and out.get("message"):
            messages.append(user(out["message"]))
    return messages
