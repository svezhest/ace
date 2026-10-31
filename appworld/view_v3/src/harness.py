"""AppWorld agent loop (ReAct code agent).

Builds the conversation from the prompt in src/ (its {{ ... }} slots filled by the benchmark, see
bridge.py), asks the model for the next step, runs the first ```python block of the reply in the
task's REPL and shows the output, until the benchmark ends the episode. Runs the hooks from hooks.py;
code that a hook sends back is not run.
"""
import copy
import re
from pathlib import Path

import bridge
import hooks

SRC = Path(__file__).parent
FULL_CODE = r"```python\n(.*?)```"
PARTIAL_CODE = r".*```python\n(.*)"


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


def make_ctx(messages, episode, history, output="", code=""):
    return {
        "messages": copy.deepcopy(messages),
        "observation": history["last_observations"][-1] if history["last_observations"] else "",
        "output": output,
        "code": code,
        "step": episode.steps,
        "max_step": bridge.STEP_LIMIT,
        "remaining_steps": bridge.STEP_LIMIT - episode.steps,
        "history": copy.deepcopy(history),
    }


def run(episode, llm):
    """Play one episode. `llm(messages)` returns the assistant message. Returns the conversation."""
    nb = {}
    history = {"last_actions": [], "last_observations": []}
    messages = text_to_messages(episode.fill(prompt("starting_prompt.md").lstrip()) + "\n\n")
    out = call_hook("on_init", make_ctx(messages, episode, history), nb) or {}
    skills = [s["text"] for s in out.get("skills") or [] if isinstance(s, dict) and s.get("text")]
    if skills:
        messages[-1]["content"] += ("Some tips that may help for this task:\n"
                                    + "\n".join(f"- {s}" for s in skills) + "\n\n")

    while not episode.finished:
        out = call_hook("make_pre_hint", make_ctx(messages, episode, history), nb)
        if out and out.get("message"):
            messages.append(user(out["message"]))

        reply = llm(messages)
        action, text = extract_code(reply.get("content") or "")
        reply["content"] = text + "\n\n"
        messages.append(reply)

        out = call_hook("on_before_action", make_ctx(messages, episode, history, text, action), nb)
        if out and out.get("kind") == "block_and_prompt":
            messages.append(user(out.get("message") or "Harness blocked this code. Write another step."))
            continue

        obs = episode.execute(action)
        if obs is None:
            break
        messages.append(output_message(obs))
        history["last_actions"].append(action)
        history["last_observations"].append(obs)

        out = call_hook("on_post_step", make_ctx(messages, episode, history, text, action), nb)
        if out and out.get("kind") == "inject_hint" and out.get("message"):
            messages.append(user(out["message"]))
    return messages
