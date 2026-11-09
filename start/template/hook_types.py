"""What harness.py hands to each hook in hooks.py, and what a hook may return."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Step:
    """One step the benchmark has taken: exactly what was sent and what came back."""
    action: str
    observation: str


@dataclass(frozen=True)
class EpisodeStart:
    task: str
    step_limit: int


@dataclass(frozen=True)
class BeforeModelCall:
    earlier_steps: tuple[Step, ...]
    current_observation: str
    steps_left: int


@dataclass(frozen=True)
class BeforeAction:
    """The model has replied; `proposed_action` has not been sent to the benchmark yet."""
    proposed_action: str
    earlier_steps: tuple[Step, ...]
    current_observation: str
    steps_left: int


@dataclass(frozen=True)
class AfterStep:
    """`step` has just been taken; it is not in `earlier_steps`."""
    step: Step
    earlier_steps: tuple[Step, ...]
    steps_left: int


@dataclass(frozen=True)
class Tips:
    """Added to the system prompt."""
    tips: list[str]


@dataclass(frozen=True)
class Hint:
    """`message` is added to the conversation as a user message."""
    message: str


@dataclass(frozen=True)
class Block:
    """The proposed action is not sent; `message` goes to the model instead and it replies again."""
    message: str
