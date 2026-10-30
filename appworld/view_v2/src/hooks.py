"""Hooks called by src/harness.py. All optional; define any of them as `def name(ctx, nb)`.

A hook returns a dict to inject into the conversation, or None to do nothing. See the contract at the
top of src/harness.py. A hook that raises is ignored by the harness.

These hooks address the main way the agent loses tasks: it gets stuck repeating the same action and
observation, then burns the whole step budget (reason "step limit") instead of finishing.
"""


def _identical_observations(history, window=3):
    """Return True if the last `window` observations in `history` are all exactly equal.

    `history` is the run's history dict (see harness.make_ctx); it has a `last_observations` list of the
    strings the environment returned for the last steps. If the model keeps running the same code and gets
    the same output, nothing new is learned, so it is almost certainly looping. Comparing the *output*
    rather than the code is deliberate: it also catches a model that tweaks its code but still gets the
    same result, while ignoring a model that legitimately changes its code between two similar-looking
    outputs (which would not be a loop).
    """
    obs = history.get("last_observations") or []
    if len(obs) < window:
        return False
    return all(obs[-window] == obs[-window - i] for i in range(1, window))


def on_post_step(ctx, nb):
    """Break a loop the moment the environment has given the same result for several steps in a row.

    After the environment has returned an identical output for `window` consecutive steps, tell the model
    to stop and either complete the task or change its approach. This is the safety net that stops a stuck
    model before it wastes the remaining steps, so it fails less often on tasks where it otherwise would.
    """
    if _identical_observations(ctx["history"], 3):
        return {"kind": "inject_hint", "message": (
            "You are repeating the same action and getting the same result. This is not making progress.\n"
            "Stop now. If you have already solved the task, call apis.supervisor.complete_task() to finish. "
            "Otherwise change your approach and try something different.\n"
        )}
    return None
