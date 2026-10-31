# ALFWorld agent harness

- `src/` — source code of the agent harness. This is what you edit.
  - `harness.py` — the agent loop: builds the conversation from the prompts in `src/` and the task's messages; hands each model reply to the task; calls the hooks.
  - `hooks.py` — hooks called by `harness.py`; at start each one returns None (changes nothing).
  - `*.md` — prompts used by `harness.py`; `starting_prompt.md` is the system prompt.
  - `bridge.py` — connection to the benchmark (the AgentBench ALFWorld task, a black box): gives the task's messages, hands it the model's replies, says when and how it ended the episode. Do not edit.
- `logs/` — runs of this harness.
  - `run_N.jsonl` — one episode as a stream of events, one per line. `event` says who produced it: `bridge` — a call through the bridge (`start`; `send`: a model reply handed to the task, `turn` — its number, `not_shown` — the task's messages the harness did not put into the conversation; `end`: how the task ended the episode — `finished`, `step limit`, `error` with `detail`); `prompt` — the system message built from `src/starting_prompt.md`; `env` — a message of the task, as the model received it; `model` — the model's reply; `harness` — other messages from the harness (`from`: its file in `src/`). The `message` fields in order are the conversation as the model saw it.
  - `results.jsonl` — one line per run: `{run, ok, reason}`.
  - Read the failed runs; the passed runs are there for comparison and grep.
