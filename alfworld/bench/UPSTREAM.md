# The benchmark: AgentBench ALFWorld task, as published

`agentbench_alfworld/` — files of https://github.com/THUDM/AgentBench at d1e4a10db08c87075c78972e48ecc182be03e2d5
(`src/server/tasks/alfworld/`, last changed in 5bf4eb2 «publish agentbench_fc», 2025-10-09), not modified.
Runs on `agentrl-worker==0.4.0` (Task, Session, typings) and the `alfworld` package of `.venv`.
Harness-R1 (DeepExperience/Harness-R1@2b3f125) uses the same task with its own harness inside; the task's
rules (action parser, repeated actions, turn loop, success) are the same, its parameters: max_step 50.

`fixture.py` runs one episode the way agentrl's TaskWorker does, without HTTP; the only fixtures: task
parameters, a one-game split file, `$ALFWORLD_DATA/logic`, the task's log line about repeated actions.

sha256:
```
fe5c050977146b2c11e3b2b951a5e44ebe147004a52e0af3975f9b36526c9e95  __init__.py
e74b0dd1216dd5b394bce98ffecf5f351be44b0a223a4dd6777f84d0e36c1bbf  task.py
3cdb6c1803d73876243a5472ee01a993abdb150f4991a4ea73bbf1f30cb743c6  utils.py
f998657ed4e9396d5cf01c2c3aa42da22896ba04109788320b12911d39ed7ced  environment.py
d95e445ae3b3fc1f277a6ebd613678bf2c46a39a4975d8a12a85d642e8d40016  configs/base_config.yaml
65cf9eb0552dc30a6f00d4f6ec43cd90593359b083b01c31e856f27fac272d8d  prompts/alfworld_multiturn_plan_first.json
```
Check: replaying the 38 logs of `view/` (made with the previous bridge, which re-implemented these
rules) through `view_v3/src` and this task gives the same conversations byte for byte and the same
ok/reason (`tools/replay.py`).
