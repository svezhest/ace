"""Hooks called by harness.py; ctx is a copy of what the agent has seen (make_ctx), nb a dict kept for the episode."""


def on_init(ctx, nb):
    return None


def make_pre_hint(ctx, nb):
    return None


def on_before_action(ctx, nb):
    return None


def on_post_step(ctx, nb):
    return None
