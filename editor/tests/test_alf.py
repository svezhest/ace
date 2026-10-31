# Копия tests/test_harness.py бенчмарка: SRC и ROOT из окружения (editor/check.py). Остальное как в оригинале.
"""Stub-model tests for view_v3/src (harness + bridge) on the AgentBench task, and runner/run.py. No LLM calls.

  cd ~/Projects/nrhsi/alfworld && .venv/bin/python -m pytest -q tests
"""
import json
import os
import subprocess
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(os.environ["BENCH_ROOT"])
SRC = Path(os.environ["EDITOR_SRC"])  # editor: проверяемая копия src/
sys.dont_write_bytecode = True
sys.path[:0] = [str(SRC), str(ROOT / "runner"), str(ROOT / "bench")]
os.environ.setdefault("ALFWORLD_DATA", str(ROOT / "data" / "alfworld"))

import bridge  # noqa: E402
import fixture  # noqa: E402
import harness  # noqa: E402
from events import Recorder, events, honest  # noqa: E402
from fake import Fake  # noqa: E402
from run import expert_hint  # noqa: E402
from llm import EpisodeEnd  # noqa: E402

SPLITS = json.loads((ROOT / "splits.json").read_text())
GAME = SPLITS["train"][0]


def expert_plan(game=GAME):
    return expert_hint(game, 2).removeprefix("expert plan: ").split("; ")


def play(script, hooks=None, game=GAME, guard=False):
    rec = Recorder(fixture.Episode(game, os.environ["ALFWORLD_DATA"]))
    ep = bridge.Episode(rec)
    llm = Fake(script)
    old = harness.hooks
    harness.hooks = hooks if hooks is not None else types.SimpleNamespace()
    try:
        try:
            msgs = harness.run(ep, bridge.guard(ep, llm) if guard else llm)
        except (EpisodeEnd, bridge.Loop):
            msgs = llm.conversation
    finally:
        harness.hooks = old
        rec.bench.close()
    return ep, rec, llm, msgs


def test_hooks_file_is_empty():
    ns = {}
    exec((SRC / "hooks.py").read_text(), ns)
    names = sorted(k for k, v in ns.items() if callable(v))
    assert names == ["make_pre_hint", "on_before_action", "on_init", "on_post_step"]
    assert all(ns[n]({}, {}) is None for n in names)


def test_success_with_expert_actions():
    ep, rec, llm, msgs = play(expert_plan())
    assert rec.bench.won() and ep.finished and ep.end == {"reason": "finished", "status": "completed"}
    assert msgs[0] == {"role": "system", "content": (SRC / "starting_prompt.md").read_text()}
    assert msgs[1]["role"] == "user" and msgs[1]["content"].startswith("Here is your task. ")
    assert honest(rec.sent(), llm.outputs) and rec.sent() == llm.outputs


def test_message_shapes_and_sources():
    """Every message is a model reply, a src/ prompt, or the task's text in the baseline format."""
    script = [{"text": "thinking out loud"}, {"args": "not json"}] + expert_plan()
    ep, rec, llm, msgs = play(script)
    prompts = {(SRC / n).read_text() for n in ("no_tool_call.md", "invalid_tool_call.md")}
    assert msgs[2]["role"] == "assistant" and "tool_calls" not in msgs[2]
    assert msgs[3]["content"] == (SRC / "no_tool_call.md").read_text()
    assert msgs[5]["content"] == (SRC / "invalid_tool_call.md").read_text()
    assert ep.turns == len(script)  # replies without a usable tool call are turns too
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
    ep, rec, llm, msgs = play(["look"])
    assert ep.end == {"reason": "error", "status": "agent invalid action", "detail": "repeated action"}
    assert not rec.bench.won() and len(llm.calls) == 4  # the task's rule: the last 3 actions identical


def test_guard_ends_a_loop_without_turns():
    def block(ctx, nb):
        return {"kind": "block_and_prompt", "message": "blocked"}

    ep, rec, llm, msgs = play(["look"], hooks=types.SimpleNamespace(on_before_action=block), guard=True)
    assert ep.end == {"reason": "error", "detail": "repeated reply"} and ep.finished
    assert ep.turns == 0 and len(llm.calls) == 3  # three same replies, none handed to the task


def test_guard_in_the_runner():
    import run
    r = run.play({"run": 1, "game": GAME, "src": str(SRC), "fake": [{"text": "x"}], "gen": None,
                  "hint_level": 0, "wall_limit": 600})
    assert r["reason"] == "repeated reply" and r["meta"]["turns"] == 3 and r["meta"]["model_calls"] == 3
    assert r["events"][-1] == {"event": "bridge", "call": "end", "reason": "error", "detail": "repeated reply"}


def test_turn_limit_of_the_task():
    ep, rec, llm, msgs = play([{"text": "x"}, "look", "inventory"] * 30)
    assert ep.turns == bridge.STEP_LIMIT and ep.end["reason"] == "step limit"


def test_game_step_limit():
    ep, rec, llm, msgs = play(["look", "inventory"] * 30)
    assert ep.turns == bridge.STEP_LIMIT and rec.env_steps() == bridge.STEP_LIMIT and ep.finished
    assert ep.end == {"reason": "step limit", "status": "completed", "detail": "the game's limit of 50 actions"}


def test_noop_hooks_do_not_change_conversation():
    script = [{"text": "x"}] + expert_plan()[:3] + ["look", "inventory"]

    def none(ctx, nb):
        nb["seen"] = nb.get("seen", 0) + 1
        ctx["observation"] = "mutated"  # ctx is a copy
        return None

    noop = types.SimpleNamespace(on_init=none, make_pre_hint=none, on_before_action=none, on_post_step=none)
    a = play(script)[3]
    b = play(script, hooks=noop)[3]
    assert a == b


def test_hook_effects_reach_conversation():
    seen = {}

    def on_init(ctx, nb):
        seen["init_obs"] = ctx["observation"]
        return {"skills": [{"text": "tip one"}], "tool_hint": "Use exact names."}

    def make_pre_hint(ctx, nb):
        return {"message": "pre hint"} if ctx["step"] == 0 and not nb.get("hinted") and not nb.update(hinted=1) else None

    def on_before_action(ctx, nb):
        if ctx["output"] == "inventory":
            return {"kind": "block_and_prompt", "message": "blocked"}
        return None

    def broken(ctx, nb):
        raise RuntimeError("bad hook")

    hooks = types.SimpleNamespace(on_init=on_init, make_pre_hint=make_pre_hint,
                                  on_before_action=on_before_action, on_post_step=broken)
    ep, rec, llm, msgs = play(["inventory", "look", "look", "look"], hooks=hooks)
    assert msgs[0]["content"].endswith("\n\nSome tips that may help for this task:\n- tip one")
    assert msgs[2] == {"role": "user", "content": "pre hint"}
    assert msgs[4] == {"role": "user", "content": "blocked"}
    assert "Your task is to" in seen["init_obs"]
    assert ep.turns == len(llm.calls) - 1  # the blocked reply was not handed to the task


def test_honest_check():
    a, b = {"role": "assistant", "content": "a"}, {"role": "assistant", "content": "b"}
    assert honest([a, b], [a, {"role": "assistant", "content": "x"}, b])
    assert not honest([b, a], [a, b])
    assert not honest([{"role": "assistant", "content": "made up"}], [a, b])


def test_events_cover_the_conversation():
    script = [{"text": "x"}] + expert_plan()
    ep, rec, llm, msgs = play(script)
    ev = events(msgs, rec, ep.end, SRC)
    assert ev[0] == {"event": "bridge", "call": "start"}  # the task's system prompt == src/starting_prompt.md
    assert ev[1]["event"] == "prompt" and ev[2]["event"] == "env"
    sends = [e for e in ev if e.get("call") == "send"]
    assert [e["turn"] for e in sends] == list(range(1, len(script) + 1))
    assert sends[0]["not_shown"][0]["role"] == "user"  # the task's own message, replaced by src/no_tool_call.md
    assert any(e["event"] == "harness" and e.get("from") == "src/no_tool_call.md" for e in ev)
    assert ev[-1] == {"event": "bridge", "call": "end", "reason": "finished", "status": "agent validation failed"}


def test_runner_files(tmp_path):
    """run.py with the stub model writes run_N.jsonl as events and results.jsonl {run, ok, reason}."""
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
            ev = [json.loads(l) for l in (view / "logs" / f"run_{n}.jsonl").read_text().splitlines()]
            msgs = [e["message"] for e in ev if "message" in e]
            assert msgs[0]["role"] == "system" and msgs[1]["role"] == "user"
            assert all(set(m) <= {"role", "content", "tool_calls", "tool_call_id"} for m in msgs)
            assert ev[-1]["event"] == "bridge" and ev[-1]["call"] == "end"
        meta = [json.loads(l) for l in (ROOT / "runs" / tag / "meta.jsonl").read_text().splitlines()]
        assert all(m["append_only"] and m["honest"] for m in meta)
        assert not list((view / "src").glob("__pycache__"))
    finally:
        shutil.rmtree(ROOT / "runs" / tag, ignore_errors=True)


@pytest.mark.parametrize("level", [1, 2])
def test_hint_levels(level):
    h = expert_hint(GAME, level)
    assert h.startswith("an expert solves" if level == 1 else "expert plan: ")


def test_upstream_files_unchanged():
    import hashlib
    import re
    text = (ROOT / "bench" / "UPSTREAM.md").read_text()
    want = dict((p, h) for h, p in re.findall(r"^([0-9a-f]{64})  (\S+)$", text, flags=re.M))
    assert len(want) == 6
    for p, h in want.items():
        assert hashlib.sha256((ROOT / "bench" / "agentbench_alfworld" / p).read_bytes()).hexdigest() == h, p


def test_close_cancels_an_unfinished_task():
    """The harness stops first (here: the stub model runs out): the task is cancelled, its thread ends."""
    import threading
    rec = Recorder(fixture.Episode(GAME, os.environ["ALFWORLD_DATA"]))
    ep = bridge.Episode(rec)
    llm = Fake(["look", "inventory"], max_calls=3)
    with pytest.raises(EpisodeEnd):
        harness.run(ep, llm)
    rec.bench.close()
    assert not ep.finished and rec.bench.final.status == "cancelled"
    assert not [t for t in threading.enumerate() if not t.daemon and t is not threading.main_thread()]
