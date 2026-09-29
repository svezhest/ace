# ace

A bench of in-context learning methods (ACE, Dynamic Cheatsheet, SCOPE, TF-GRPO, EvoLib, GEPA, MCE). Fidelity to the
upstream implementations is checked with live records: the upstream runs as is, a proxy logs its requests to the
model, and the port of the method replays the same log.

| where | what |
|---|---|
| `records/<record>/` | upstream record runner (`run.sh`, `run.json`) and the record itself (`rec.jsonl`, upstream output) |
| `upstreams/` | upstream repositories, git submodules at the pinned commits |
| `records/setup_envs.sh` | upstream environments for the records: venvs, data, caches (`upstreams/.venvs`, `.data`, `.hf`, `.hf-evolib`, `.tiktoken`) and docker images |
| `tools/record/` | record and replay proxy (`record.py`), embeddings server (`embeddings.py`) |
| `tests/test_record.py` | proxy tests |

Setup: `git clone --recursive`, then `records/setup_envs.sh` (or `records/setup_envs.sh gepa light ...` for some
environments only). `UPSTREAMS` points the runners and the setup to another upstreams directory with the same layout.
