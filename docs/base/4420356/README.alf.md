# ALFWorld agent harness

- `src/` — the harness of the agent: the prompts and the code that run it on a task. This is what you edit.
  - `harness.py` — the agent loop; `hooks.py` — functions that `harness.py` calls; `hook_types.py` — what each of them is given and may return.
  - `*.md` — prompts; `starting_prompt.md` is the system prompt.
  - `bridge.py` — connection to the benchmark. Not part of the harness: do not edit.
- `logs/` — runs of the harness in `src/` as it was at the start.
  - `run_N.jsonl` — one episode as a stream of events, one per line. `event` says who produced it: `bridge` — a call through the bridge (`start`; `send`: a model reply handed to the task, `turn` — its number, `not_shown` — the task's messages the harness did not put into the conversation; `end`: how the task ended the episode — `finished`, `step limit`, `error` with `detail`); `prompt` — the system message built from `src/starting_prompt.md`; `env` — a message of the task, as the model received it; `model` — the model's reply; `harness` — other messages from the harness (`from`: its file in `src/`). The `message` fields in order are the conversation as the model saw it.
  - `results.jsonl` — one line per run: `{run, ok, reason}`.
- `tests/rerun.py` — replays the runs recorded in `logs/` on the current `src/`. The model's replies and the task's messages are taken from the log, so neither the model nor the benchmark is called. As long as what the harness gives the model and the task is the same as in the log, the log still describes the run; at the first place where it differs, the replay of that run stops and the difference is printed: `-` what the log has there, `+` what the harness does now. From that point on the rest of the log no longer applies. It also shows the hooks whose answer changed compared with `src/` as it was at the start (a copy of it is in `tests/orig_src/`). `no changes` means that in those runs the current `src/` gives the model and the task exactly what the log has. `python3 tests/rerun.py` prints one line per group of runs that behave the same way; `python3 tests/rerun.py N` shows run N in detail, with the line of `logs/run_N.jsonl`. An example, from the harness of another agent, where a hook was added that says "foobar" when the observation has both "foo" and "bar" in it:
```
$ python3 tests/rerun.py
runs 2, 5, 9 (1 failed, 2 passed): no changes (same as the log to the end)
runs 1, 3, 4, 6, 7, 8 (4 failed, 2 passed): diverges at model call: failed — run 1 at 12, run 3 at 17, run 4 at 17, run 7 at 30; passed — run 6 at 12, run 8 at 30: what the model sees differs from the log (e.g. run 1)
  + user: foobar
  hook on_observation: {"message": "foobar"} (was None)
$ python3 tests/rerun.py 3
run 3 (failed): diverges at model call 17 (log line 52): what the model sees differs from the log
  - assistant: The foo is next to the bar, I will take the foo. | act: take foo
  + user: foobar
  hook on_observation at model call 17: {"message": "foobar"} (was None)
```
`python3 tests/rerun.py N --at K` replays run N on the current `src/` up to model call K and shows, for the step just before it, the lines of the log and every call of a function in `src/harness.py` and `src/hooks.py`, with the values it got and returned: the values the harness really has at that point of the run. An example, from the same other agent:
```
$ python3 tests/rerun.py 3 --at 17
run 3 (failed), before model call 17 (log line 52):
  the log just before it:
    assistant: I will look in the box. | act: open box
    tool: The box is open. In it you see a foo and a bar.
  calls of the functions in src/harness.py and src/hooks.py, with the values they got and returned:
    harness.make_ctx({'observation': 'The box is open. In it you see a foo and a bar.'}, {'actions': [... 12 more, 'go to box', 'open box']}) -> {'observation': 'The box is open. In it you see a foo and a bar.', 'step': 16, 'history': {'actions': [... 12 more, 'go to box', 'open box']}}
    harness.call_hook('on_observation', <same as above>) -> {'message': 'foobar'}
      hooks.on_observation(<same as above>) -> {'message': 'foobar'}
```
- `tests/runs.py` — reads the runs recorded in `logs/`. `python3 tests/runs.py steps N` prints run N in short, one line per model call: its number, the log line, what the model sent → the first line of what came back (`steps N 20-30`: calls 20-30). The call numbers are those in the output of `tests/rerun.py`. `python3 tests/runs.py show N 40-45` prints lines 40-45 of the log in full.
- `tests/smoke.py` — a smoke test: runs src/harness.py with a stub benchmark and a stub model (not the benchmark) and prints what the harness adds to the conversation after which model reply, or the error. Run it with `python3 tests/smoke.py`.
