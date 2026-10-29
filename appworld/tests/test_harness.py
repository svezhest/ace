"""Stub-model tests for view/src (harness + bridge), runner/llm.py and runner/run.py. No LLM calls.
The benchmark process (runner/env_server.py in AppWorld's venv) is real.

  cd ~/Projects/nrhsi/appworld && .venv/bin/python -m pytest -q tests
"""
import json
import os
import shutil
import subprocess
import sys
import types
from pathlib import Path

import pytest
import requests

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "view" / "src"
sys.dont_write_bytecode = True
sys.path[:0] = [str(SRC), str(ROOT / "runner")]

import bridge  # noqa: E402
import harness  # noqa: E402
import llm as llm_mod  # noqa: E402
from fake import Fake  # noqa: E402
from llm import EpisodeEnd  # noqa: E402
from run import APPWORLD, Benchmark, hint  # noqa: E402

UPSTREAM_PROMPT = APPWORLD / "repo/experiments/prompts/react_code_agent/instructions.txt"
UPSTREAM_RUN = APPWORLD / "experiments/outputs/ornith9b_react_dev"  # upstream agent, logged lm_calls
SPLITS = json.loads((ROOT / "splits.json").read_text())
TASK = SPLITS["train"][0]
PRINT_SET = "Let me look.\n\n```python\nprint({'rock', 'jazz', 'pop', 'indie', 'folk', 'soul'})\n```\nThen more."
COMPLETE = "Done.\n\n```python\napis.supervisor.complete_task()\n```"


def play(script, task=TASK, hooks=None, tmp=None):
    """-> (messages, llm, completed, evaluation)."""
    old = harness.hooks
    harness.hooks = hooks if hooks is not None else types.SimpleNamespace()
    root = Path(tmp)
    (root / "data").symlink_to(APPWORLD / "data")
    bench = Benchmark(task, "test", root, root / "env.log")
    llm = Fake(script)
    try:
        ep = bridge.Episode(bench.url)
        try:
            msgs = harness.run(ep, llm)
        except EpisodeEnd:
            msgs = llm.conversation
        completed = ep.done
        evaluation = bench.finish()
    finally:
        bench.close()
        harness.hooks = old
        (root / "data").unlink()
    return msgs, llm, completed, evaluation


@pytest.fixture
def tmp(tmp_path):
    return tmp_path


def test_start_state():
    assert (SRC / "hooks.py").read_text() == ""
    assert (SRC / "starting_prompt.md").read_bytes() == UPSTREAM_PROMPT.read_bytes()


def test_extract_code_matches_upstream_cases():
    assert harness.extract_code("a\n```python\nx = 1\n```\nb\n```python\ny\n```") == ("x = 1", "a\n```python\nx = 1\n```")
    assert harness.extract_code("a\n```python\nx = 1\n") == ("x = 1", "a\n```python\nx = 1\n```")
    assert harness.extract_code("a\n```python\nx = 1") == ("x = 1", "a\n```python\nx = 1\n```")
    assert harness.extract_code("no code") == ("", "no code")


@pytest.mark.skipif(not UPSTREAM_RUN.exists(), reason="upstream run not available")
def test_replay_equals_upstream_requests(tmp):
    """Upstream model replies fed back: every request equals what upstream AppWorld sent; same evaluation."""
    task = "0d8a4ee_1"
    calls = [json.loads(l) for l in open(UPSTREAM_RUN / "tasks" / task / "logs" / "lm_calls.jsonl")]
    msgs, llm, completed, ev = play([c["output"]["choices"][0]["message"]["content"] for c in calls], task, tmp=tmp)
    strip = lambda ms: [{"role": m["role"], "content": m["content"]} for m in ms]
    assert [strip(r) for r in llm.requests] == [strip(c["input"]["messages"]) for c in calls]
    assert completed and ev["success"]


def test_message_shapes_and_no_leaks(tmp):
    msgs, llm, completed, ev = play(["thinking, no code", PRINT_SET, COMPLETE], tmp=tmp)
    assert completed and not ev["success"] and len(llm.calls) == 3
    n_prompt = len(llm.requests[0])
    assert [m["role"] for m in msgs[:n_prompt]][:2] == ["user", "assistant"]
    assert msgs[n_prompt - 1]["content"].endswith("\n\n") and "{{" not in json.dumps(msgs)
    rest = msgs[n_prompt:]
    assert [m["role"] for m in rest] == ["assistant", "user"] * 3
    assert rest[0]["content"] == "thinking, no code\n\n"
    assert rest[1]["content"] == "Output:\n```\nNo code available to execute.\n```\n\n"
    assert rest[2]["content"].endswith("```\n\n") and "Then more" not in rest[2]["content"]
    for m in rest[1::2]:
        assert m["content"].startswith("Output:\n```\n") and m["content"].endswith("```\n\n")
    assert all(set(m) == {"role", "content"} for m in msgs)
    text = json.dumps(msgs)
    for leak in (TASK, "ground_truth", "experiment", "evaluation", "test_"):
        assert leak not in text


def test_reproducible_across_processes(tmp_path):
    (tmp_path / "a").mkdir(), (tmp_path / "b").mkdir()
    a = play([PRINT_SET, COMPLETE], tmp=tmp_path / "a")[0]
    b = play([PRINT_SET, COMPLETE], tmp=tmp_path / "b")[0]
    assert a == b


def test_step_limit(tmp):
    msgs, llm, completed, ev = play(["```python\nprint(1)\n```"], tmp=tmp)
    assert not completed and len(llm.calls) == bridge.STEP_LIMIT == harness.MAX_STEPS


def test_noop_hooks_do_not_change_conversation(tmp_path):
    def none(ctx, nb):
        nb["seen"] = nb.get("seen", 0) + 1
        ctx["messages"].clear()  # ctx is a copy
        return None

    noop = types.SimpleNamespace(on_init=none, make_pre_hint=none, on_before_action=none, on_post_step=none)
    (tmp_path / "a").mkdir(), (tmp_path / "b").mkdir()
    a = play([PRINT_SET, COMPLETE], tmp=tmp_path / "a")[0]
    b = play([PRINT_SET, COMPLETE], hooks=noop, tmp=tmp_path / "b")[0]
    assert a == b


def test_hook_effects_reach_conversation(tmp):
    seen = {}

    def on_init(ctx, nb):
        seen["task_msg"] = ctx["messages"][-1]["content"]
        return {"skills": [{"text": "tip one"}]}

    def make_pre_hint(ctx, nb):
        return {"message": "pre hint"} if ctx["step"] == 0 else None

    def on_before_action(ctx, nb):
        if "print(1)" in ctx["action"]["code"]:
            return {"kind": "block_and_prompt", "message": "blocked"}
        if "print(2)" in ctx["action"]["code"]:
            return {"kind": "rewrite_action", "action": "print(3)"}
        return None

    def broken(ctx, nb):
        raise RuntimeError("bad hook")

    hooks = types.SimpleNamespace(on_init=on_init, make_pre_hint=make_pre_hint,
                                  on_before_action=on_before_action, on_post_step=broken)
    msgs, llm, completed, ev = play(["```python\nprint(1)\n```", "```python\nprint(2)\n```", COMPLETE],
                                    hooks=hooks, tmp=tmp)
    n = len(llm.requests[0]) - 1  # pre hint is the last message of the first request
    assert "Task: " in seen["task_msg"]
    assert msgs[n - 1]["content"].endswith("Some tips that may help for this task:\n- tip one\n\n")
    assert msgs[n] == {"role": "user", "content": "pre hint"}
    assert msgs[n + 2] == {"role": "user", "content": "blocked"}
    assert msgs[n + 4]["content"] == "Output:\n```\n3\n```\n\n"
    assert completed


def test_transport_body_and_endings(monkeypatch):
    sent = []

    class R:
        def __init__(self, code, body):
            self.status_code, self._b = code, body
            self.text = json.dumps(body)

        def json(self):
            return self._b

    ok = {"choices": [{"message": {"role": "assistant", "content": "<think>r</think>hi", "refusal": None},
                       "finish_reason": "stop"}], "usage": {"prompt_tokens": 5, "completion_tokens": 1}}
    replies = []
    monkeypatch.setattr(llm_mod.requests, "post", lambda url, json, **kw: sent.append(json) or replies.pop(0))
    monkeypatch.setattr(llm_mod.time, "sleep", lambda s: None)
    c = llm_mod.Client("http://x/v1", "m", step_limit=2)
    replies.append(R(200, ok))
    assert c([{"role": "user", "content": "q"}]) == {"role": "assistant", "content": "hi", "reasoning_content": "r"}
    assert sent[0] == {"model": "m", "messages": [{"role": "user", "content": "q"}], "temperature": 0.0, "seed": 100}
    replies.append(R(400, {"error": "This model's maximum context length is 65536 tokens"}))
    with pytest.raises(EpisodeEnd, match="context exhausted"):
        c([])
    replies.extend([R(500, {"e": 1})] * 3)
    with pytest.raises(EpisodeEnd, match="model error"):
        c([])

    def timeout(*a, **k):
        raise requests.ReadTimeout()
    monkeypatch.setattr(llm_mod.requests, "post", timeout)
    with pytest.raises(EpisodeEnd, match="timeout"):
        c([])
    c.calls = [{}] * 2
    with pytest.raises(EpisodeEnd, match="step limit"):
        c([])


def test_hint_levels():
    ev = {"num_tests": 3, "failures": [{"requirement": "assert  a\n b."}]}
    assert hint(ev, 0) is None
    assert hint(ev, 1) == "2 of 3 checks passed"
    assert hint(ev, 2) == "2 of 3 checks passed; failed: assert a b."


def test_runner_files(tmp_path):
    """run.py with the stub model writes run_N.jsonl in chat form and results.jsonl {run, ok, reason}."""
    view = tmp_path / "view"
    (view / "logs").mkdir(parents=True)
    shutil.copytree(SRC, view / "src", ignore=shutil.ignore_patterns("__pycache__"))
    tag = f"pytest_{os.getpid()}"
    cmd = [sys.executable, str(ROOT / "runner" / "run.py"), "--view", str(view), "--fake", json.dumps([COMPLETE]),
           "--tasks", SPLITS["train"][1], SPLITS["val"][0], "--workers", "2", "--tag", tag]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        rows = [json.loads(l) for l in (view / "logs" / "results.jsonl").read_text().splitlines()]
        assert rows == [{"run": 1, "ok": False, "reason": "wrong result"}, {"run": 2, "ok": False, "reason": "wrong result"}]
        for n in (1, 2):
            msgs = [json.loads(l) for l in (view / "logs" / f"run_{n}.jsonl").read_text().splitlines()]
            assert msgs[0]["role"] == "user" and msgs[-1]["content"].startswith("Output:")
            assert all(set(m) == {"role", "content"} for m in msgs)
        meta = [json.loads(l) for l in (ROOT / "runs" / tag / "meta.jsonl").read_text().splitlines()]
        assert all(m["append_only"] and m["completed"] for m in meta)
        assert not list((view / "src").glob("__pycache__"))
        bad = subprocess.run(cmd[:-2] + ["--tasks", "x_1", "--tag", tag + "b"], capture_output=True, text=True)
        assert bad.returncode != 0 and "outside train/val" in bad.stderr
    finally:
        shutil.rmtree(ROOT / "runs" / tag, ignore_errors=True)
