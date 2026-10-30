# AppWorld agent harness

- `src/` — source code of the agent harness. This is what you edit.
  - `harness.py` — the agent loop: builds the conversation from the prompt in `src/`, runs the code from the model's replies and shows the output; calls the hooks.
  - `hooks.py` — hooks called by `harness.py`; at start each one returns None (changes nothing).
  - `starting_prompt.md` — the prompt used by `harness.py`. `{{ ... }}` in it are slots that the benchmark fills with the task's values (list in `bridge.py`); the slot names are fixed.
  - `bridge.py` — connection to the benchmark: fills the slots, runs code in the task's environment. Do not edit.
- `logs/` — runs of this harness.
  - `run_N.jsonl` — one episode's conversation, one message per line, as sent to and received from the model.
  - `results.jsonl` — one line per run: `{run, ok, reason}`.
  - Read the failed runs; the passed runs are there for comparison and grep.
