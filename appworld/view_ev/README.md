# AppWorld agent harness

- `src/` — source code of the agent harness. This is what you edit.
  - `harness.py` — the agent loop: builds the conversation from the prompt in `src/`, runs the code from the model's replies and shows the output; calls the hooks.
  - `hooks.py` — hooks called by `harness.py` (contracts at the top of `harness.py`). Empty at start.
  - `starting_prompt.md` — the prompt used by `harness.py`. `{{ ... }}` in it are slots that the benchmark fills with the task's values (list in `bridge.py`); the slot names are fixed.
  - `bridge.py` — connection to the benchmark: fills the slots, runs code in the task's environment. Do not edit.
- `logs/` — runs of this harness.
  - `run_N.jsonl` — one episode as a stream of events, one per line. `event` says who produced it: `bridge` — a call to the benchmark (`fill`: the values put into the prompt's slots; `reset`, `step`, `execute`: what was sent to the environment); `prompt` — a message the harness built from `src/starting_prompt.md`; `env` — a message with the benchmark's result, as the model received it; `model` — the model's reply; `harness` — other messages from the harness (`from`: its file in `src/`). The `message` fields in order are the conversation as the model saw it.
  - `results.jsonl` — one line per run: `{run, ok, reason}`.
  - Read the failed runs; the passed runs are there for comparison and grep.
