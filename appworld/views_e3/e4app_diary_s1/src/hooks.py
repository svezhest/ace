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
    return None
