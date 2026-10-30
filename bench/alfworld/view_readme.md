# ALFWorld agent harness

- `src/` — source code of the agent harness. This is what you edit.
  - `harness.py` — the agent loop: builds the conversation from the prompts in `src/` and the environment's observations; calls the hooks.
  - `hooks.py` — hooks called by `harness.py`; at start each one returns None (changes nothing).
  - `*.md` — prompts used by `harness.py`; `starting_prompt.md` is the system prompt.
  - `bridge.py` — connection to the benchmark: gives the task, executes actions, checks success. Do not edit.
- `logs/` — runs of this harness.
  - `run_N.jsonl` — one episode's conversation, one message per line, as sent to and received from the model.
  - `results.jsonl` — one line per run: `{run, ok, reason}`.
  - Read the failed runs; the passed runs are there for comparison and grep.
