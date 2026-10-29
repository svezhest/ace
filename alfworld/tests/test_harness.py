"""Stub-model tests for view/src (harness + bridge) and runner/run.py. No LLM calls.

  cd ~/Projects/nrhsi/alfworld && .venv/bin/python -m pytest -q tests
"""
import json
import os
import subprocess
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "view" / "src"
sys.dont_write_bytecode = True
sys.path[:0] = [str(SRC), str(ROOT / "runner")]
os.environ.setdefault("ALFWORLD_DATA", str(ROOT / "data" / "alfworld"))

import bridge  # noqa: E402
import harness  # noqa: E402
from fake import Fake  # noqa: E402
from llm import EpisodeEnd  # noqa: E402

SPLITS = json.loads((ROOT / "splits.json").read_text())
GAME = SPLITS["train"][0]


def expert_plan(game=GAME):
    return bridge.Episode(game).hint(2).removeprefix("expert plan: ").split("; ")


def play(script, hooks=None, game=GAME):
    ep = bridge.Episode(game)
    llm = Fake(script)
    old = harness.hooks
    harness.hooks = hooks if hooks is not None else types.SimpleNamespace()
    try:
        try:
            msgs = harness.run(ep, llm)
        except EpisodeEnd as e:
            msgs = llm.conversation
            ep.end_reason = e.reason
    finally:
        harness.hooks = old
    return ep, llm, msgs


def test_hooks_file_is_empty():
    assert (SRC / "hooks.py").read_text().strip() == ""


def test_success_with_expert_actions():
    ep, llm, msgs = play(expert_plan())
    assert ep.won and ep.done and ep.end_reason == "success"
    assert msgs[0] == {"role": "system", "content": (SRC / "starting_prompt.md").read_text()}
    assert msgs[1]["role"] == "user" and msgs[1]["content"].startswith("Here is your task. ")


def test_message_shapes_and_sources():
    """Every message is a model reply, a src/ prompt, or bridge text in the baseline format."""
    script = [{"text": "thinking out loud"}, {"args": "not json"}] + expert_plan()
    ep, llm, msgs = play(script)
    prompts = {(SRC / n).read_text() for n in ("no_tool_call.md", "invalid_tool_call.md")}
    assert msgs[2]["role"] == "assistant" and "tool_calls" not in msgs[2]
    assert msgs[3]["content"] == (SRC / "no_tool_call.md").read_text()
    assert msgs[5]["content"] == (SRC / "invalid_tool_call.md").read_text()
    ids = set()
    for m in msgs[2:]:
        if m["role"] == "assistant":
            ids = {c["id"] for c in m.get("tool_calls", [])}
        elif m["role"] == "tool":
            assert m["tool_call_id"] in ids
            body, sep, acts = m["content"].partition(" AVAILABLE ACTIONS: ")
            assert sep and acts.endswith("\n") and body
        else:
            assert m["content"] in prompts
    text = json.dumps(msgs)
    for leak in (GAME, "tw-pddl", "policy", "expert", "pick_"):
        assert leak not in text


def test_repeated_action_ends_episode():
    ep, llm, msgs = play(["look"])
    assert ep.done and not ep.won and ep.end_reason == "repeated action"
    assert len(llm.calls) == 4  # benchmark rule: 4th step with the last 3 actions identical


def test_step_limit():
    ep, llm, msgs = play(["look", "inventory"] * 30)
    assert not ep.done and len(llm.calls) == bridge.STEP_LIMIT


def test_noop_hooks_do_not_change_conversation():
    script = [{"text": "x"}] + expert_plan()[:3] + ["look", "inventory"]

    def none(ctx, nb):
        nb["seen"] = nb.get("seen", 0) + 1
        ctx["observation"] = "mutated"  # ctx is a copy
        return None

    noop = types.SimpleNamespace(on_init=none, make_pre_hint=none, on_before_action=none, on_post_step=none)
    _, _, a = play(script)
    _, _, b = play(script, hooks=noop)
    assert a == b


def test_hook_effects_reach_conversation():
    seen = {}

    def on_init(ctx, nb):
        seen["init_obs"] = ctx["observation"]
        return {"skills": [{"text": "tip one"}], "tool_hint": "Use exact names."}

    def make_pre_hint(ctx, nb):
        return {"message": "pre hint"} if ctx["step"] == 0 else None

    def on_before_action(ctx, nb):
        if ctx["action"]["final_action"] == "inventory":
            return {"kind": "block_and_prompt", "message": "blocked"}
        return None

    def broken(ctx, nb):
        raise RuntimeError("bad hook")

    hooks = types.SimpleNamespace(on_init=on_init, make_pre_hint=make_pre_hint,
                                  on_before_action=on_before_action, on_post_step=broken)
    ep, llm, msgs = play(["inventory", "look", "look", "look"], hooks=hooks)
    assert msgs[0]["content"].endswith("\n\nSome tips that may help for this task:\n- tip one")
    assert msgs[2] == {"role": "user", "content": "pre hint"}
    assert msgs[4] == {"role": "user", "content": "blocked"}
    assert "Your task is to" in seen["init_obs"]


def test_runner_files(tmp_path):
    """run.py with the stub model writes run_N.jsonl in chat form and results.jsonl {run, ok, reason}."""
    view = tmp_path / "view"
    (view / "logs").mkdir(parents=True)
    import shutil
    shutil.copytree(SRC, view / "src", ignore=shutil.ignore_patterns("__pycache__"))
    tag = f"pytest_{os.getpid()}"
    script = json.dumps(expert_plan(SPLITS["train"][1]))
    cmd = [sys.executable, str(ROOT / "runner" / "run.py"), "--view", str(view), "--fake", script,
           "--games", SPLITS["train"][1], SPLITS["train"][2], "--workers", "2", "--tag", tag]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        rows = [json.loads(l) for l in (view / "logs" / "results.jsonl").read_text().splitlines()]
        assert [set(r) for r in rows] == [{"run", "ok", "reason"}] * 2
        assert rows[0] == {"run": 1, "ok": True, "reason": "success"}
        assert rows[1]["ok"] is False
        for n in (1, 2):
            msgs = [json.loads(l) for l in (view / "logs" / f"run_{n}.jsonl").read_text().splitlines()]
            assert msgs[0]["role"] == "system" and msgs[1]["role"] == "user"
            assert all(set(m) <= {"role", "content", "tool_calls", "tool_call_id"} for m in msgs)
        meta = [json.loads(l) for l in (ROOT / "runs" / tag / "meta.jsonl").read_text().splitlines()]
        assert all(m["append_only"] for m in meta)
        assert not list((view / "src").glob("__pycache__"))
    finally:
        shutil.rmtree(ROOT / "runs" / tag, ignore_errors=True)


@pytest.mark.parametrize("level", [1, 2])
def test_hint_levels(level):
    h = bridge.Episode(GAME).hint(level)
    assert h.startswith("an expert solves" if level == 1 else "expert plan: ")
