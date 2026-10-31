"""ALFWorld agent loop.

Builds the conversation from the prompts in src/ and the task's messages from bridge.py, asks the
model for one action per turn (tool `take_action`), hands each reply to the task and runs the hooks
from hooks.py. The task ends the episode; a reply that a hook sends back is not handed to the task.
"""
import copy
import json
from pathlib import Path

import bridge
import hooks

SRC = Path(__file__).parent
ACTIONS = " AVAILABLE ACTIONS: "  # how the task lists the valid actions after its text

TOOLS = [{
    "type": "function",
    "function": {
        "name": "take_action",
        "description": "Take one of the offered actions. Choose the action from the AVAILABLE ACTIONS list given by the task and place its exact text in the action argument, as in this example: take_action(action=\"go to cabinet 1\").",
        "parameters": {
            "type": "object",
            "properties": {"action": {"type": "string", "description": "The exact text of one of the offered available actions, e.g. \"go to cabinet 1\"."}},
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


def split_actions(text):
    """Task text -> (observation, valid actions)."""
    text, _, actions = text.partition(ACTIONS)
    return text, [a for a in actions.strip().split("\n") if a]


def action_of(reply):
    """The action string of the reply's first tool call, or None."""
    try:
        return list(json.loads(reply["tool_calls"][0]["function"]["arguments"]).values())[0]
    except Exception:
        return None


def is_admissible(action, admissible):
    """Whether the action text matches one of the offered available actions."""
    if action is None:
        return False
    a = action.strip().lower()
    for offered in admissible or []:
        if offered.strip().lower() == a:
            return True
    return False


def make_ctx(state, episode, history, raw=""):
    return {
        "observation": state["observation"],
        "admissible": list(state["admissible"]),
        "output": raw,
        "step": episode.turns,
        "max_step": bridge.STEP_LIMIT,
        "remaining_steps": bridge.STEP_LIMIT - episode.turns,
        "history": copy.deepcopy(history),
    }


def run(episode, llm):
    """Play one episode. `llm(messages, tools)` returns the assistant message. Returns the conversation."""
    nb = {}
    history = {"last_actions": [], "last_observations": []}
    tools = copy.deepcopy(TOOLS)
    first = [m for m in episode.start() if m["role"] == "user"]  # the task's own system prompt is replaced
    obs, admissible = split_actions(first[0]["content"])
    state = {"observation": obs, "admissible": admissible}

    system = prompt("starting_prompt.md")
    out = call_hook("on_init", make_ctx(state, episode, history), nb) or {}
    skills = [s["text"] for s in out.get("skills") or [] if isinstance(s, dict) and s.get("text")]
    if skills:
        system += "\n\nSome tips that may help for this task:\n" + "\n".join(f"- {s}" for s in skills)
    if out.get("tool_hint"):
        fn = tools[0]["function"]
        fn["description"] = f"{fn['description']}\n\n{out['tool_hint']}".strip()

    messages = [{"role": "system", "content": system}] + first

    while not episode.finished:
        out = call_hook("make_pre_hint", make_ctx(state, episode, history), nb)
        if out and out.get("message"):
            messages.append(user(out["message"]))

        reply = llm(messages, tools)
        messages.append(reply)
        raw = action_of(reply)

        out = call_hook("on_before_action", make_ctx(state, episode, history, raw or ""), nb)
        if out and out.get("kind") == "block_and_prompt":
            messages.append(user(out.get("message") or "Harness blocked this action. Choose a valid action."))
            continue

        for m in episode.send(reply):
            if m["role"] == "tool":
                messages.append(m)
                obs, admissible = split_actions(m["content"])
                state = {"observation": obs, "admissible": admissible}
                history["last_actions"].append((raw or "").strip().lower())
                history["last_observations"].append(obs.strip().lower())
            elif m["role"] == "user":  # the task did not take the reply as an action
                messages.append(user(prompt("no_tool_call.md" if not reply.get("tool_calls") else "invalid_tool_call.md")))
        if messages[-1]["role"] == "tool":
            out = call_hook("on_post_step", make_ctx(state, episode, history, raw or ""), nb)
            if out and out.get("kind") == "inject_hint" and out.get("message"):
                messages.append(user(out["message"]))
    return messages
