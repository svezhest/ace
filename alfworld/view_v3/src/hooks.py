"""Hooks called by harness.py. Each gets a snapshot of the episode at that moment (hook_types.py) and `memory`,
a dict kept for the episode; each returns None to change nothing."""
from hook_types import AfterStep, BeforeAction, BeforeModelCall, Block, EpisodeStart, Hint, Tips


def on_init(start: EpisodeStart, memory: dict) -> Tips | None:
    return None


def make_pre_hint(now: BeforeModelCall, memory: dict) -> Hint | None:
    return None


def on_before_action(now: BeforeAction, memory: dict) -> Block | None:
    return None


def on_post_step(now: AfterStep, memory: dict) -> Hint | None:
    return None
