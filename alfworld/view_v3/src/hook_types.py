"""What harness.py hands to each hook in hooks.py, and what a hook may return."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Step:
    """One action the task has taken: exactly what the model sent and what the task answered."""
    action: str
    observation: str


@dataclass(frozen=True)
class EpisodeStart:
    task: str
    valid_actions: tuple[str, ...]
    turn_limit: int


@dataclass(frozen=True)
class BeforeModelCall:
    earlier_steps: tuple[Step, ...]
    current_observation: str
    valid_actions: tuple[str, ...]
    turns_left: int


@dataclass(frozen=True)
class BeforeAction:
    """The model has replied; `proposed_action` has not been sent to the task yet."""
    proposed_action: str
    earlier_steps: tuple[Step, ...]
    current_observation: str
    valid_actions: tuple[str, ...]
    turns_left: int


@dataclass(frozen=True)
class AfterStep:
    """`step` has just been taken; it is not in `earlier_steps`."""
    step: Step
    earlier_steps: tuple[Step, ...]
    valid_actions: tuple[str, ...]
    turns_left: int


@dataclass(frozen=True)
class Tips:
    """`tips` are added to the system prompt, `action_tool_note` to the description of the tool `take_action`."""
    tips: list[str]
    action_tool_note: str = ""


@dataclass(frozen=True)
class Hint:
    """`message` is added to the conversation as a user message."""
    message: str


@dataclass(frozen=True)
class Block:
    """The proposed action is not sent; `message` goes to the model instead and it replies again."""
    message: str
