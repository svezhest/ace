# AppWorld agent harness

- `src/` — source code of the agent harness. This is what you edit.
  - `harness.py` — the agent loop: builds the conversation from the prompt in `src/`, hands the code from the model's replies to the benchmark and shows the output; calls the hooks.
  - `hooks.py` — hooks called by `harness.py`; at start each one returns None (changes nothing).
  - `starting_prompt.md` — the prompt used by `harness.py`. `{{ ... }}` in it are slots that the benchmark fills with the task's values (list in `bridge.py`); the slot names are fixed.
  - `bridge.py` — connection to the benchmark (AppWorld's own agent loop, a black box): fills the slots, has code run in the task's environment, says when and how the loop ended the episode. Do not edit.
- `logs/` — runs of this harness.
  - `run_N.jsonl` — one episode as a stream of events, one per line. `event` says who produced it: `bridge` — a call to the benchmark (`fill`: the values put into the prompt's slots; `execute`: code run by the benchmark, `step` — its number; `end`: how the benchmark ended the episode — `finished`, `step limit`, `error`); `prompt` — a message the harness built from `src/starting_prompt.md`; `env` — a message with the benchmark's output, as the model received it; `model` — the model's reply; `harness` — other messages from the harness (`from`: its file in `src/`). The `message` fields in order are the conversation as the model saw it.
  - `results.jsonl` — one line per run: `{run, ok, reason}`.
  - Read the failed runs; the passed runs are there for comparison and grep.
