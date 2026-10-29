"""Bridge to the ALFWorld benchmark (TextWorld text mode). Not part of the harness: do not edit.

This is the only place that knows the benchmark. It does what the benchmark's own task
runner (AgentBench ALFWorld task, as used by Harness-R1) does:
  - gives the task: the opening message with the room, the goal and the valid actions;
  - executes an action and returns what the environment says, followed by the valid actions;
  - matches a free-form action string to the closest valid action (the benchmark's parser);
  - ends the episode when the game is won, or when the same action was sent 3 times in a row;
  - checks success: the game's own `won` flag.

Black box: the game engine (TextWorld + ALFWorld game files) behind `Episode`.
The agent never sees anything about the solution.
"""
import os

import numpy as np
import textworld
from alfworld.agents.environment.alfred_tw_env import AlfredDemangler, AlfredInfos
from nltk.translate.bleu_score import SmoothingFunction, sentence_bleu

STEP_LIMIT = 50  # turns (model replies) per episode in the benchmark protocol


def available_actions(actions):
    return " AVAILABLE ACTIONS: " + "\n".join(actions) + "\n"


def strip_location(observation):
    # "You arrive at loc 17. On the armchair 1, ..." -> "On the armchair 1, ..."
    if observation.startswith("You arrive at loc "):
        observation = observation[observation.find(". ") + 2:]
    return observation


def bleu(reference, candidate):
    return sentence_bleu([reference.split()], candidate.split(),
                         smoothing_function=SmoothingFunction().method4)


def match_action(action, choices, limit=0.01):
    """Benchmark's action parser: first line, lowercased, else the most similar valid action."""
    action = action.strip().lower().split("\n")[0]
    if not choices or action in choices:
        return action
    scores = [bleu(choice, action) for choice in choices]
    best = int(np.argmax(np.array(scores)))
    return choices[best] if scores[best] > limit else action


class Episode:
    def __init__(self, game_file, data_root=None):
        root = data_root or os.environ["ALFWORLD_DATA"]
        self.game_file = os.path.join(root, game_file)
        self.observation = ""   # last environment text, without the action list
        self.admissible = []    # actions valid right now
        self.done = False
        self.won = False
        self.end_reason = None  # "success" | "repeated action" when the bridge ends the episode
        self._sent = []         # raw action strings of executed steps
        self._env = None

    def reset(self):
        """Start the game. Returns the opening user message."""
        infos = textworld.EnvInfos(won=True, admissible_commands=True, extras=["gamefile"])
        self._env = textworld.start(self.game_file, request_infos=infos,
                                    wrappers=[AlfredDemangler(shuffle=False), AlfredInfos])
        state = self._env.reset()
        self.observation = "\n".join(state.feedback.split("\n\n")[1:])  # drop the welcome banner
        self.admissible = list(state["admissible_commands"])
        return "Here is your task. " + self.observation + available_actions(self.admissible)

    def match(self, raw_action):
        return match_action(raw_action, self.admissible)

    def step(self, action, raw_action):
        """Execute `action`. Returns the tool-result text the agent sees."""
        state, _, _ = self._env.step(action)
        self.observation = strip_location(state.feedback)
        self.admissible = list(state["admissible_commands"])
        self.won = bool(state["won"])
        self._sent.append(raw_action)
        if len(self._sent) > 3 and len(set(self._sent[-3:])) == 1:
            self.done, self.won, self.end_reason = True, False, "repeated action"
        elif self.won:
            self.done, self.end_reason = True, "success"
        return self.observation + available_actions(self.admissible)

    def close(self):
        if self._env is not None:
            self._env.close()

    def hint(self, level):
        """Benchmark feedback for results.jsonl beyond ok/reason (ablation axis; 0 = none).
        1: how many steps an expert planner needs from the start (difficulty, no solution).
        2: the expert plan itself (reference solution)."""
        if level <= 0:
            return None
        infos = textworld.EnvInfos(policy_commands=True)
        env = textworld.start(self.game_file, request_infos=infos,
                              wrappers=[AlfredDemangler(shuffle=False), AlfredInfos])
        plan = list(env.reset()["policy_commands"] or [])
        env.close()
        if level == 1:
            return f"an expert solves this task in {len(plan)} steps"
        return "expert plan: " + "; ".join(plan)
