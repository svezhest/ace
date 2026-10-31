"""Hooks called by harness.py; ctx is a copy of what the agent has seen (make_ctx), nb a dict kept for the episode."""


def on_init(ctx, nb):
    return None


def make_pre_hint(ctx, nb):
    return None


def on_before_action(ctx, nb):
    return None


def on_post_step(ctx, nb):
    return None


def on_completed(ctx, nb):
    """Called after complete_task has run and the benchmark has marked the episode finished.

    ctx["verdict"] is the benchmark's verdict (episode.end). Return a message to show the model the
    benchmark's verdict, so a wrong answer is not mistaken for a success and can be corrected."""
    verdict = ctx.get("verdict") or {}
    reason = verdict.get("reason") if isinstance(verdict, dict) else str(verdict)
    message = f"The task was marked {reason}."
    if reason == "step limit":
        message += (f" You ran out of steps. This usually means the model was repeating the same step "
                    f"or restarting the task over and over. Look at the recent steps in the conversation "
                    f"and, if you are repeating or restarting, call "
                    f"apis.supervisor.complete_task to finish.")
    if reason == "error":
        message += (" The benchmark errored. Look at the recent steps in the conversation for the error, "
                    "and, if the task is not actually done, try again; otherwise call "
                    "apis.supervisor.complete_task to finish.")
    if reason == "fail":
        message += " The task was marked as failed."
    return {"message": message}
