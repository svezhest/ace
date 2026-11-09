"""ALFWorld agent loop.

Builds the conversation from the prompts in src/ and the task's messages from bridge.py, asks the
model for one action per turn (tool `take_action`), hands each reply to the task and runs the hooks
from hooks.py. The task ends the episode; an action that a hook blocks is not handed to the task.
"""
import copy
import json
from pathlib import Path

import bridge
import hooks
from hook_types import AfterStep, BeforeAction, BeforeModelCall, Block, EpisodeStart, Hint, Step, Tips

SRC = Path(__file__).parent
ACTIONS = " AVAILABLE ACTIONS: "  # how the task lists the valid actions after its text
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


def call_hook(hook, moment, memory, may_return):
    out = hook(moment, memory)
    if out is not None and not isinstance(out, may_return):
        raise TypeError(f"hooks.{hook.__name__} returned {type(out).__name__}, expected {may_return.__name__} or None")
    return out


def split_actions(text):
    """Task text -> (observation, valid actions)."""
    text, _, actions = text.partition(ACTIONS)
    return text, tuple(a for a in actions.strip().split("\n") if a)


def action_of(reply):
    """The action string of the reply's first tool call, or None."""
    try:
        return list(json.loads(reply["tool_calls"][0]["function"]["arguments"]).values())[0]
    except Exception:
        return None


def run(episode, llm):
    """Play one episode. `llm(messages, tools)` returns the assistant message. Returns the conversation."""
    memory = {}
    steps = []
    tools = copy.deepcopy(TOOLS)
    first = [m for m in episode.start() if m["role"] == "user"]  # the task's own system prompt is replaced
    observation, valid_actions = split_actions(first[0]["content"])
    system = prompt("starting_prompt.md")
    start = call_hook(hooks.on_init, EpisodeStart(
        task=observation, valid_actions=valid_actions, turn_limit=bridge.STEP_LIMIT), memory, Tips)
    if start and start.tips:
        system += "\n\nSome tips that may help for this task:\n" + "\n".join(f"- {t}" for t in start.tips)
    if start and start.action_tool_note:
        fn = tools[0]["function"]
        fn["description"] = f"{fn['description']}\n\n{start.action_tool_note}".strip()
    messages = [{"role": "system", "content": system}] + first

    while not episode.finished:
        turns_left = bridge.STEP_LIMIT - episode.turns
        hint = call_hook(hooks.make_pre_hint, BeforeModelCall(
            earlier_steps=tuple(steps), current_observation=observation, valid_actions=valid_actions,
            turns_left=turns_left), memory, Hint)
        if hint:
            messages.append(user(hint.message))

        reply = llm(messages, tools)
        messages.append(reply)
        action = action_of(reply) or ""

        block = call_hook(hooks.on_before_action, BeforeAction(
            proposed_action=action, earlier_steps=tuple(steps), current_observation=observation,
            valid_actions=valid_actions, turns_left=turns_left), memory, Block)
        if block:
            messages.append(user(block.message))
            continue

        for m in episode.send(reply):
            if m["role"] == "tool":
                messages.append(m)
                observation, valid_actions = split_actions(m["content"])
                steps.append(Step(action, observation))
            elif m["role"] == "user":  # the task did not take the reply as an action
                messages.append(user(prompt("no_tool_call.md" if not reply.get("tool_calls") else "invalid_tool_call.md")))
        if messages[-1]["role"] != "tool":  # no action was taken: no post-step hook
            continue

        hint = call_hook(hooks.on_post_step, AfterStep(
            step=steps[-1], earlier_steps=tuple(steps[:-1]), valid_actions=valid_actions,
            turns_left=bridge.STEP_LIMIT - episode.turns), memory, Hint)
        if hint:
            messages.append(user(hint.message))
    return messages
