"""AppWorld agent loop (ReAct code agent).

Builds the conversation from the prompt in src/ (its {{ ... }} slots filled by the benchmark, see
bridge.py), asks the model for the next step, runs the first ```python block of the reply in the
task's REPL and shows the output, until the task is marked complete or the step limit is reached.
Runs the hooks from hooks.py.
"""
import copy
import re
from pathlib import Path

import hooks

SRC = Path(__file__).parent
MAX_STEPS = 50
FULL_CODE = r"```python\n(.*?)```"
PARTIAL_CODE = r".*```python\n(.*)"


def prompt(name):
    return (SRC / name).read_text()


def user(text):
    return {"role": "user", "content": text}


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


def call_hook(name, ctx, nb):
    fn = getattr(hooks, name, None)
    if fn is None:
        return None
    try:
        out = fn(copy.deepcopy(ctx), nb)
    except Exception:
        return None
    return out if isinstance(out, dict) else None


def make_ctx(messages, step, history, reply="", code="", remaining=None):
    return {
        "messages": copy.deepcopy(messages),
        "observation": history["last_observations"][-1] if history["last_observations"] else "",
        "output": reply,
        "code": code,
        "step": step,
        "max_step": MAX_STEPS,
        "remaining_steps": MAX_STEPS - step if remaining is None else remaining,
        "history": copy.deepcopy(history),
    }


def run(episode, llm):
    """Play one episode. `llm(messages)` returns the assistant message. Returns the conversation."""
    nb = {}
    history = {"last_actions": [], "last_observations": []}
    messages = text_to_messages(episode.fill(prompt("starting_prompt.md").lstrip()) + "\n\n")

    out = call_hook("on_init", make_ctx(messages, 0, history), nb) or {}
    skills = [s["text"] for s in out.get("skills") or [] if isinstance(s, dict) and s.get("text")]
    if skills:
        messages[-1]["content"] += ("Some tips that may help for this task:\n"
                                    + "\n".join(f"- {s}" for s in skills) + "\n\n")
    forced = None  # code forced by on_post_step for the next turn

    for step in range(MAX_STEPS):
        out = call_hook("make_pre_hint", make_ctx(messages, step, history), nb)
        if out and out.get("message"):
            messages.append(user(out["message"]))

        reply = llm(messages)
        code, text = extract_code(reply.get("content") or "")
        reply["content"] = text + "\n\n"
        messages.append(reply)
        if forced:
            code, forced = forced, None

        out = call_hook("on_before_action", make_ctx(messages, step, history, text, code), nb)
        if out and out.get("kind") == "block_and_prompt":
            messages.append(user(out.get("message") or "Harness blocked this code. Write another step."))
            continue
        if out and out.get("kind") in ("rewrite_action", "force_action") and out.get("action"):
            code = out["action"]
            if out.get("message"):
                messages.append(user(out["message"]))

        output = episode.execute(code)
        messages.append(output_message(output))
        history["last_actions"].append(code)
        history["last_observations"].append(output)

        out = call_hook("on_post_step", make_ctx(messages, step, history, text, code, MAX_STEPS - step - 1), nb)
        if out and out.get("kind") == "inject_hint" and out.get("message"):
            messages.append(user(out["message"]))
        if out and out.get("kind") == "force_action" and out.get("action"):
            forced = out["action"]
            if out.get("message"):
                messages.append(user(out["message"]))

        if episode.done:
            break
    return messages
