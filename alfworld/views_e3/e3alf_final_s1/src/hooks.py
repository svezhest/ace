"""Hooks called by harness.py; ctx is a copy of what the agent has seen (make_ctx), nb a dict kept for the episode.

The harness computes, for every step, the observation, the admissible actions, the step number, how many
steps remain, the whole history and the model's last output; the hooks can turn that context into help
for the model (skills, a tool hint, a pre-turn hint) or into a decision about the model's chosen action
(block_and_prompt) or a hint injected after a step (inject_hint).
"""
import bridge


def on_init(ctx, nb):
    return None


def make_pre_hint(ctx, nb):
    """Surface how many steps remain and flag that the model is repeating an action, before its turn."""
    return _pre_hint(ctx)


def on_before_action(ctx, nb):
    """Inspect the model's chosen action before it is taken.

    Return nothing (or a dict without "kind") to accept the action. Return
    {"kind": "block_and_prompt", "message": "..."} to reject an invalid / clearly
    off-task action and ask the model to choose a valid one instead.
    """
    return _maybe_block(ctx)


def on_post_step(ctx, nb):
    """Optional hint injected into the conversation right after the action was taken."""
    return None


def _maybe_block(ctx):
    """Reject the chosen action when it is not admissible or is obviously a wasted / looping turn."""
    admissible = ctx.get("admissible") or []
    action = (ctx.get("output") or "").strip()
    if not action:
        # No action string at all: stop the model from declaring victory with a plain-text reply.
        return {"kind": "block_and_prompt",
                "message": "You must choose one of the available actions and call the tool with it. "
                           "There is no such thing as finishing without taking an action."}

    if not admissible:
        return {"kind": "block_and_prompt",
                "message": "No valid actions were listed. Choose one of the available actions and call the tool."}

    chosen = action.lower()
    valid = {a.lower() for a in admissible}
    if chosen not in valid:
        return {"kind": "block_and_prompt",
                "message": "That action is not among the available actions. "
                           "Choose one of the available actions and call the tool with it."}

    # The action is admissible, but the model is wasting turns by repeating one after one.
    history = ctx.get("history") or {}
    last_actions = [str(a).strip().lower() for a in history.get("last_actions", [])]
    if len(last_actions) >= 2 and last_actions[-1] == chosen and last_actions[-2] == chosen:
        return {"kind": "block_and_prompt",
                "message": "You are repeating the same action. Choose a different available action."}

    return None


def _pre_hint(ctx):
    """A short pre-turn hint: how many steps remain and whether the model is looping."""
    message = ""
    if ctx.get("remaining_steps", bridge.STEP_LIMIT) <= 5:
        message = f"You have {ctx.get('remaining_steps', bridge.STEP_LIMIT)} step(s) left. Be decisive: pick the best available action now."
    history = ctx.get("history") or {}
    last_actions = [str(a).strip().lower() for a in history.get("last_actions", [])]
    if len(last_actions) >= 3 and last_actions[-1] == last_actions[-2] == last_actions[-3]:
        message = "You are repeating the same action. Choose a different available action."
    return {"message": message} if message else None
