"""ALFWorld agent loop.

Builds the conversation from the prompts in src/ and the observations from bridge.py,
asks the model for one action per turn (tool `take_action`) and runs the hooks from hooks.py.

Hooks (all optional; define any of them in hooks.py as `def name(ctx, nb)`):
  on_init(ctx, nb)          -> {"skills": [{"text": TEXT}], "tool_hint": TEXT} or None
                               skills are added to the system prompt, tool_hint to the tool description
  make_pre_hint(ctx, nb)    -> {"message": TEXT} or None             user message before the model's turn
  on_before_action(ctx, nb) -> {"kind": "block_and_prompt", "message": TEXT}           action not executed
                               {"kind": "rewrite_action", "action": TEXT, "message": TEXT}
                               {"kind": "force_action", "action": TEXT, "message": TEXT}
                               or None
  on_post_step(ctx, nb)     -> {"kind": "inject_hint", "message": TEXT}                 user message
                               {"kind": "force_action", "action": TEXT, "message": TEXT} next action
                               or None
ctx is a read-only copy of what the agent has seen (see make_ctx); nb is a dict kept for the episode.
A hook that raises is ignored.
"""
import copy
import json
from pathlib import Path

import hooks

SRC = Path(__file__).parent
MAX_STEPS = 50

TOOLS = [{
    "type": "function",
    "function": {
        "name": "take_action",
        "description": "Take an action.",
        "parameters": {
            "type": "object",
            "properties": {"action": {"type": "string", "description": "The action you would like to take"}},
            "required": ["action"],
            "additionalProperties": False,
        },
    },
}]


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


def make_ctx(episode, step, history, raw="", action="", remaining=None):
    normalized = (action or raw).strip().lower()
    return {
        "observation": episode.observation,
        "admissible": list(episode.admissible),
        "output": raw,
        "action": {"raw": raw, "normalized": normalized, "final_action": action,
                   "in_admissible": normalized in episode.admissible},
        "step": step,
        "max_step": MAX_STEPS,
        "remaining_steps": MAX_STEPS - step if remaining is None else remaining,
        "history": copy.deepcopy(history),
    }


def run(episode, llm):
    """Play one episode. `llm(messages, tools)` returns the assistant message. Returns the conversation."""
    nb = {}
    history = {"last_actions": [], "last_observations": []}
    tools = copy.deepcopy(TOOLS)
    first = episode.reset()

    system = prompt("starting_prompt.md")
    out = call_hook("on_init", make_ctx(episode, 0, history), nb) or {}
    skills = [s["text"] for s in out.get("skills") or [] if isinstance(s, dict) and s.get("text")]
    if skills:
        system += "\n\nSome tips that may help for this task:\n" + "\n".join(f"- {s}" for s in skills)
    if out.get("tool_hint"):
        fn = tools[0]["function"]
        fn["description"] = f"{fn['description']}\n\n{out['tool_hint']}".strip()

    messages = [{"role": "system", "content": system}, user(first)]
    forced = None  # action forced by on_post_step for the next turn

    for step in range(MAX_STEPS):
        out = call_hook("make_pre_hint", make_ctx(episode, step, history), nb)
        if out and out.get("message"):
            messages.append(user(out["message"]))

        reply = llm(messages, tools)
        messages.append(reply)
        calls = reply.get("tool_calls") or []
        if not calls:
            messages.append(user(prompt("no_tool_call.md")))
            continue
        try:
            call = calls[0]
            raw = list(json.loads(call["function"]["arguments"]).values())[0]
            action = episode.match(raw)
        except Exception:
            messages.append(user(prompt("invalid_tool_call.md")))
            continue
        if forced:
            action, forced = forced, None

        out = call_hook("on_before_action", make_ctx(episode, step, history, raw, action), nb)
        if out and out.get("kind") == "block_and_prompt":
            messages.append(user(out.get("message") or "Harness blocked this action. Choose a valid action."))
            continue
        if out and out.get("kind") in ("rewrite_action", "force_action") and out.get("action"):
            action = out["action"].strip().lower()
            if out.get("message"):
                messages.append(user(out["message"]))

        result = episode.step(action, raw)
        messages.append({"role": "tool", "tool_call_id": call["id"], "content": result})
        history["last_actions"].append(action)
        history["last_observations"].append(episode.observation.strip().lower())

        out = call_hook("on_post_step", make_ctx(episode, step, history, raw, action, MAX_STEPS - step - 1), nb)
        if out and out.get("kind") == "inject_hint" and out.get("message"):
            messages.append(user(out["message"]))
        if out and out.get("kind") == "force_action" and out.get("action"):
            forced = out["action"].strip().lower()
            if out.get("message"):
                messages.append(user(out["message"]))

        if episode.done:
            break
    return messages
