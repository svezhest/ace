# ALFWorld agent harness

- `src/` — source code of the agent harness. This is what you edit.
  - `harness.py` — the agent loop: builds the conversation from the prompts in `src/` and the environment's observations; calls the hooks.
  - `hooks.py` — hooks called by `harness.py` (contracts at the top of `harness.py`). Empty at start.
  - `*.md` — prompts used by `harness.py`; `starting_prompt.md` is the system prompt.
  - `bridge.py` — connection to the benchmark: gives the task, executes actions, checks success. Do not edit.
- `logs/` — runs of this harness.
  - `run_N.jsonl` — one episode as a stream of events, one per line. `event` says who produced it: `bridge` — a call to the benchmark (`fill`: the values put into the prompt's slots; `reset`, `step`, `execute`: what was sent to the environment; `end`: how the episode ended — `finished`, `step limit`, `error` with `detail`); `prompt` — a message the harness built from `src/starting_prompt.md`; `env` — a message with the benchmark's result, as the model received it; `model` — the model's reply; `harness` — other messages from the harness (`from`: its file in `src/`). The `message` fields in order are the conversation as the model saw it.
  - `results.jsonl` — one line per run: `{run, ok, reason}`.
  - Read the failed runs; the passed runs are there for comparison and grep.
