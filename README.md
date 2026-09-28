# ace

A bench of in-context learning methods (ACE, Dynamic Cheatsheet, SCOPE, TF-GRPO, EvoLib, GEPA, MCE). Fidelity to the
upstream implementations is checked with live records: the upstream runs as is, a proxy logs its requests to the
model, and the port of the method replays the same log.

| where | what |
|---|---|
| `records/<record>/` | upstream record runner (`run.sh`, `run.json`) and the record itself (`rec.jsonl`, upstream output) |
| `records/setup_envs.sh` | upstream environments for the records |
| `tools/record/` | record and replay proxy (`record.py`), embeddings server (`embeddings.py`) |
| `tests/test_record.py` | proxy tests |
