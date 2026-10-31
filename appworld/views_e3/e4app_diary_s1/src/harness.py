"""AppWorld agent loop (ReAct code agent).

Builds the conversation from the prompt in src/ (its {{ ... }} slots filled by the benchmark, see
bridge.py), asks the model for the next step, runs the first ```python block of the reply in the
task's REPL and shows the output, until the benchmark ends the episode. Runs the hooks from hooks.py;
code that a hook sends back is not run.

The loop has a few safety nets that the benchmark's fixed 50-step limit alone does not provide:

- one action per step: only the first ```python block of a reply is run, and, when the model writes
  more than one such block in a single reply, a warning is shown before the first one is run so the
  model can notice and split its step.
- loop detection: if the model repeats the same code or the same output as in the previous step, it is
  told to stop repeating and, if it has nothing more to do, to call complete_task (the benchmark's
  limit would otherwise burn the whole budget on identical failing steps, and the model would be left
  with no way to finish); the comparison is exact, so a step that only reuses a line from the previous
  one is not treated as a repeat.
- the benchmark's verdict after complete_task is shown to the model, so a wrong answer is not mistaken
  for a success and can be corrected instead of being submitted as the final result.
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
    """-> (code, the whole reply kept in the conversation). Takes the first complete ```python block as
    the code to run, but keeps the entire reply (including anything after the block) in the conversation
    so the model's reasoning is not dropped or mislabeled. An unclosed block at the end is taken as is
    and closed."""
    m = re.search(FULL_CODE, text, flags=re.DOTALL)
    if m:
        return m.group(1).strip(), text
    m = re.match(PARTIAL_CODE, text, flags=re.DOTALL)
    if m:
        return m.group(1).strip(), text + ("" if text.endswith("\n") else "\n") + "```"
    return "", text


def all_python_blocks(text):
    """-> list of every ```python block's contents in text. Used to detect a reply that carries more
    than one block (the harness runs only the first, so extra blocks are dropped without the model
    knowing)."""
    return re.findall(FULL_CODE, text, flags=re.DOTALL)


def output_text(content):
    """Return the source text of the first ```python block in content, or content itself if it has no
    block. Used for loop detection on the model's reasoning, independent of what was run."""
    blocks = all_python_blocks(content)
    if blocks:
        return blocks[0].strip()
    return content


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


def make_ctx(messages, episode, history, reply="", code=""):
    return {
        "messages": copy.deepcopy(messages),
        "observation": history["last_observations"][-1] if history["last_observations"] else "",
        "output": reply,
        "code": code,
        "step": episode.steps,
        "max_step": bridge.STEP_LIMIT,
        "remaining_steps": bridge.STEP_LIMIT - episode.steps,
        "verdict": episode.end,
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
        content = reply.get("content") or ""

        # A single step should do a single thing. If the reply carries more than one ```python block,
        # only the first is run, so warn before running it and let the model notice and split the step.
        if all_python_blocks(content):
            blocks = all_python_blocks(content)
            if len(blocks) > 1:
                extra = "\n\n".join(f"- {b.strip()!r}" for b in blocks[1:])
                messages.append(user(f"This reply had more than one ```python block. Only the first is "
                                    f"run. Please split this step. Extra blocks were not run: {extra}."))

        code, text = extract_code(content)
        reply["content"] = text + "\n\n"
        messages.append(reply)

        # A reply with no code block runs empty code, which the benchmark reads as "no code to run" and
        # does not make progress. Warn instead of silently wasting a step.
        if not code:
            messages.append(user("This reply has no ```python code block to run. Write code before "
                                "asking for the next step."))

        # Loop detection: the benchmark's step limit would otherwise burn the whole budget on identical
        # failing steps. If the model is repeating the same code or the same output, warn it and let it
        # decide: it may try a genuinely different step, or, if it has nothing more to do, simply stop
        # and call complete_task.
        if history["last_actions"] and code == history["last_actions"][-1]:
            messages.append(user("You sent the same code as in the previous step. This will fail again. "
                                "Stop repeating it. If you have nothing else to try, call "
                                "apis.supervisor.complete_task to finish the task."))
            continue
        if history["last_observations"] and output_text(content) == history["last_observations"][-1]:
            messages.append(user("The previous step produced this output again. Stop repeating it. If you "
                                "have nothing else to try, call apis.supervisor.complete_task to finish "
                                "the task."))
            continue

        out = call_hook("on_before_action", make_ctx(messages, episode, history, text, code), nb)
        if out and out.get("kind") == "block_and_prompt":
            messages.append(user(out.get("message") or "Harness blocked this code. Write another step."))
            continue

        output = episode.execute(code)
        if output is None:
            break
        messages.append(output_message(output))
        history["last_actions"].append(code)
        history["last_observations"].append(output)

        # The benchmark now knows whether the task was completed correctly (this is the verdict it
        # checks after the episode). Surface it to the model, so a wrong answer is not mistaken for a
        # success and can be corrected instead of being submitted as the final result.
        if episode.finished:
            out = call_hook("on_completed", make_ctx(messages, episode, history, text, code), nb)
            if out and out.get("message"):
                messages.append(user(out["message"]))

        out = call_hook("on_post_step", make_ctx(messages, episode, history, text, code), nb)
        if out and out.get("kind") == "inject_hint" and out.get("message"):
            messages.append(user(out["message"]))
    return messages
