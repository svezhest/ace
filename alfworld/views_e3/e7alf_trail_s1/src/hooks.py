"""Hooks called by harness.py; ctx is a copy of what the agent has seen (make_ctx), nb a dict kept for the episode."""
import harness


def on_init(ctx, nb):
    return None


def make_pre_hint(ctx, nb):
    if ctx.get("remaining_steps", 0) <= 0:
        return None
    return {"message": f"You have {ctx['remaining_steps']} action(s) left before the step limit. Use them to finish the task goal rather than exploring."}


def on_before_action(ctx, nb):
    admissible = ctx.get("admissible")
    raw = (ctx.get("output") or "").strip()
    if not harness.is_admissible(raw, admissible):
        return {"kind": "block_and_prompt",
                "message": "That action is not among the offered choices. Pick one exactly as it appears in the AVAILABLE ACTIONS list, and call take_action."}
    return None


def on_post_step(ctx, nb):
    return None
