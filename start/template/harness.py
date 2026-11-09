"""Agent loop.

Builds the conversation from the prompts in src/ and the benchmark's messages from bridge.py, asks the
model for the next step, hands each step to the benchmark and runs the hooks from hooks.py, until the
benchmark ends the episode. A step that a hook blocks is not handed to the benchmark.
"""
from pathlib import Path

import bridge
import hooks
from hook_types import AfterStep, BeforeAction, BeforeModelCall, Block, EpisodeStart, Hint, Step, Tips

SRC = Path(__file__).parent


def prompt(name):
    return (SRC / name).read_text()


def user(text):
    return {"role": "user", "content": text}


def call_hook(hook, moment, memory, may_return):
    out = hook(moment, memory)
    if out is not None and not isinstance(out, may_return):
        raise TypeError(f"hooks.{hook.__name__} returned {type(out).__name__}, expected {may_return.__name__} or None")
    return out


def run(episode, llm):
    """Play one episode. `llm(messages)` returns the assistant message. Returns the conversation."""
    memory = {}
    steps = []
    observation = episode.start()
    system = prompt("starting_prompt.md")
    start = call_hook(hooks.on_init, EpisodeStart(task=observation, step_limit=bridge.STEP_LIMIT), memory, Tips)
    if start and start.tips:
        system += "\n\nSome tips that may help for this task:\n" + "\n".join(f"- {t}" for t in start.tips)
    messages = [{"role": "system", "content": system}, user(observation)]

    while not episode.finished:
        steps_left = bridge.STEP_LIMIT - episode.steps
        hint = call_hook(hooks.make_pre_hint, BeforeModelCall(
            earlier_steps=tuple(steps), current_observation=observation, steps_left=steps_left), memory, Hint)
        if hint:
            messages.append(user(hint.message))

        reply = llm(messages)
        messages.append(reply)
        action = reply.get("content") or ""

        block = call_hook(hooks.on_before_action, BeforeAction(
            proposed_action=action, earlier_steps=tuple(steps), current_observation=observation,
            steps_left=steps_left), memory, Block)
        if block:
            messages.append(user(block.message))
            continue

        observation = episode.send(action)
        messages.append(user(observation))
        steps.append(Step(action, observation))

        hint = call_hook(hooks.on_post_step, AfterStep(
            step=steps[-1], earlier_steps=tuple(steps[:-1]), steps_left=bridge.STEP_LIMIT - episode.steps),
            memory, Hint)
        if hint:
            messages.append(user(hint.message))
    return messages
