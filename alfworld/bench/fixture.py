"""One ALFWorld episode on the AgentBench task as published (bench/agentbench_alfworld, unchanged; UPSTREAM.md).

The task runs as agentrl's TaskWorker runs it: Task.start_sample with a Session on an event loop, and
the agent side talks to it through session.controller.agent_pull — what TaskWorker.start_sample and
TaskWorker.interact do behind HTTP. Fixtures, and nothing else:
  - task parameters as in Harness-R1's configs/tasks/alfworld.yaml (max_step 50, the take_action tool);
  - a split file with the one game of this episode (the task reads data/alfworld/<split>.json);
  - $ALFWORLD_DATA/logic from the alfworld package, as `alfworld-download` puts it there;
  - the task's own log line about repeated actions is kept as the detail of the end;
  - the game's own limit of actions (alfworld config, max_nb_steps_per_episode): when the game ends the
    episode at that many actions, the end is the step limit, not "finished".
"""
import asyncio
import json
import logging
import os
import shutil
import sys
import tempfile
import threading
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
UP = HERE / "agentbench_alfworld"
sys.path.insert(0, str(HERE))

from agentrl.worker.task import Session  # noqa: E402
from agentrl.worker.typings import AgentOutput, RewardHistoryItem, SampleStatus, TaskOutput  # noqa: E402

MAX_STEP = 50  # Harness-R1 configs/tasks/alfworld.yaml
TOOLS = [{"type": "function", "function": {  # configs/tasks/alfworld.yaml (AgentBench and Harness-R1)
    "name": "take_action", "description": "Take an action.",
    "parameters": {"type": "object",
                   "properties": {"action": {"type": "string", "description": "The action you would like to take"}},
                   "required": ["action"], "additionalProperties": False}}}]
REPEAT_LOG = "repeat actions for 3 times: failure"  # task.py, the repeated-action rule
_cwd_lock = threading.Lock()


class _Lines(logging.Handler):
    def __init__(self):
        super().__init__(logging.INFO)
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())


def ensure_logic(data_root):
    import alfworld
    logic = Path(data_root) / "logic"
    logic.mkdir(exist_ok=True)
    for name in ("alfred.pddl", "alfred.twl2"):
        if not (logic / name).exists():
            shutil.copy(Path(alfworld.__file__).parent / "data" / name, logic / name)


def _chat(history):
    """TaskWorker: split_history + model_dump — the chat messages, without reward items."""
    out = []
    for item in history:
        item = getattr(item, "root", item)
        if isinstance(item, RewardHistoryItem):
            continue
        out.append(item.model_dump(mode="json") if hasattr(item, "model_dump") else dict(item))
    return out


class Episode:
    """Bench side of one episode. start() and interact(reply) return what TaskWorker returns to the agent:
    {"messages": new chat messages, "status": the task's status, "finish": bool}."""

    def __init__(self, game, data_root=None):
        from agentbench_alfworld import ALFWorld
        self.data_root = str(data_root or os.environ["ALFWORLD_DATA"])
        ensure_logic(self.data_root)
        with _cwd_lock, tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "data" / "alfworld").mkdir(parents=True)
            (Path(tmp) / "data" / "alfworld" / "episode.json").write_text(json.dumps({"game": [game]}))
            old = os.getcwd()
            os.chdir(tmp)
            try:
                self.task = ALFWorld(data_path=self.data_root, config_path=str(UP / "configs" / "base_config.yaml"),
                                     prompts_path=str(UP / "prompts" / "alfworld_multiturn_plan_first.json"),
                                     split="episode", max_step=MAX_STEP, name="alfworld-std", tools=TOOLS)
            finally:
                os.chdir(old)
        self.log = _Lines()
        lg = logging.getLogger(type(self.task).__module__)
        lg.setLevel(logging.INFO)
        lg.propagate = False
        lg.handlers = [self.log]
        cfg = self.task.config
        self.game_limit = cfg[cfg["general"]["training_method"]]["training"]["max_nb_steps_per_episode"]
        self.env_steps = 0
        self.session = Session(0)
        self.final = None  # TaskOutput at the end
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.loop.run_forever, daemon=True).start()

    async def _sample(self):
        # TaskWorker.task_start_sample_wrapper
        try:
            result = await self.task.start_sample(0, self.session)
            out = TaskOutput(index=0, status=result.status, result=result.result, history=self.session.history)
        except Exception:  # noqa: BLE001
            out = TaskOutput(index=0, status=SampleStatus.TASK_ERROR, result=traceback.format_exc(),
                             history=self.session.history)
        self.final = out
        await self.session.controller.env_finish(out)

    def _pull(self, agent_output):
        env = asyncio.run_coroutine_threadsafe(self.session.controller.agent_pull(agent_output), self.loop).result()
        msgs = _chat(env.history[env.history_ptr:])
        self.env_steps += sum(m.get("role") == "tool" for m in msgs)
        return {"messages": msgs, "status": env.status.value, "finish": env.status != SampleStatus.RUNNING}

    def start(self):
        asyncio.run_coroutine_threadsafe(self._sample(), self.loop)
        return self._pull(None)

    def interact(self, reply):
        return self._pull(AgentOutput(messages=[reply]))

    def end_of(self, status):
        """How the task ended the episode, from its status and its log; no evaluation."""
        if REPEAT_LOG in self.log.lines:
            return {"reason": "error", "status": status, "detail": "repeated action"}
        if status == SampleStatus.TASK_LIMIT_REACHED.value:
            return {"reason": "step limit", "status": status}
        if status in (SampleStatus.TASK_ERROR.value, SampleStatus.CANCELLED.value):
            return {"reason": "error", "status": status, "detail": str(self.final.result)[-500:]}
        if self.env_steps >= self.game_limit:
            return {"reason": "step limit", "status": status, "detail": f"the game's limit of {self.game_limit} actions"}
        return {"reason": "finished", "status": status}

    def won(self):
        """The task's result (reward) — for results.jsonl only, never for the agent."""
        r = self.final.result if self.final else None
        return isinstance(r, dict) and r.get("result") == 1

    def close(self):
        self.loop.call_soon_threadsafe(self.loop.stop)
