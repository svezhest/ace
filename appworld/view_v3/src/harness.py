"""AppWorld agent loop (ReAct code agent).

Builds the conversation from the prompt in src/ (its {{ ... }} slots filled by the benchmark, see
bridge.py), asks the model for the next step, runs the first ```python block of the reply in the
task's REPL and shows the output, until the benchmark ends the episode. Runs the hooks from hooks.py;
code that a hook blocks is not run.
"""
import copy
import re
from pathlib import Path

import bridge
import hooks
from hook_types import AfterStep, BeforeAction, BeforeModelCall, Block, EpisodeStart, Hint, Step, Tips

SRC = Path(__file__).parent
FULL_CODE = r"```python\n(.*?)```"
PARTIAL_CODE = r".*```python\n(.*)"


def prompt(name):
    return (SRC / name).read_text()


def user(text):
    return {"role": "user", "content": text}


def call_hook(hook, moment, memory, may_return):
    out = hook(moment, memory)
    if out is not None and not isinstance(out, may_return):
        raise TypeError(f"hooks.{hook.__name__} returned {type(out).__name__}, expected {may_return.__name__} or None")
    return out


def text_to_messages(text):
    """Split the prompt into messages at the role markers "USER:\\n", "ASSISTANT:\\n", "SYSTEM:\\n"."""
    messages, start = [], 0
    for m in re.finditer("(USER|ASSISTANT|SYSTEM):\n", text, flags=re.IGNORECASE):
        if messages:
            messages[-1]["content"] = text[start:m.start()]
        elif m.start() != 0:
            raise ValueError(f"Start of the prompt has no assigned role: {text[:m.start()]}")
        messages.append({"role": m.group(1).lower(), "content": None})
        start = m.end()
    messages[-1]["content"] = text[start:]
    return messages


def extract_code(text):
    """-> (code, reply text kept in the conversation). Takes the first complete ```python block and
    cuts the reply after it; an unclosed block at the end is taken as is and closed."""
    m = re.search(FULL_CODE, text, flags=re.DOTALL)
    if m:
        return m.group(1).strip(), text[:m.end()]
    m = re.match(PARTIAL_CODE, text, flags=re.DOTALL)
    if m:
        return m.group(1).strip(), text + ("" if text.endswith("\n") else "\n") + "```"
    return "", text


def output_message(output):
    return user("Output:\n```\n" + output + ("" if output.endswith("\n") else "\n") + "```\n\n")


def run(episode, llm):
    """Play one episode. `llm(messages)` returns the assistant message. Returns the conversation."""
    memory = {}
    steps = []
    messages = text_to_messages(episode.fill(prompt("starting_prompt.md").lstrip()) + "\n\n")
    start = call_hook(hooks.on_init, EpisodeStart(
        messages=copy.deepcopy(messages), step_limit=bridge.STEP_LIMIT), memory, Tips)
    if start and start.tips:
        messages[-1]["content"] += ("Some tips that may help for this task:\n"
                                    + "\n".join(f"- {t}" for t in start.tips) + "\n\n")

    while not episode.finished:
        steps_left = bridge.STEP_LIMIT - episode.steps
        hint = call_hook(hooks.make_pre_hint, BeforeModelCall(
            messages=copy.deepcopy(messages), earlier_steps=tuple(steps), steps_left=steps_left), memory, Hint)
        if hint:
            messages.append(user(hint.message))

        reply = llm(messages)
        code, text = extract_code(reply.get("content") or "")
        reply["content"] = text + "\n\n"
        messages.append(reply)

        block = call_hook(hooks.on_before_action, BeforeAction(
            reply_text=text, proposed_code=code, messages=copy.deepcopy(messages), earlier_steps=tuple(steps),
            steps_left=steps_left), memory, Block)
        if block:
            messages.append(user(block.message))
            continue

        output = episode.execute(code)
        if output is None:
            break
        messages.append(output_message(output))
        steps.append(Step(code, output))

        hint = call_hook(hooks.on_post_step, AfterStep(
            step=steps[-1], reply_text=text, messages=copy.deepcopy(messages), earlier_steps=tuple(steps[:-1]),
            steps_left=bridge.STEP_LIMIT - episode.steps), memory, Hint)
        if hint:
            messages.append(user(hint.message))
    return messages
