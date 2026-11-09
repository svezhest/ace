"""What harness.py hands to each hook in hooks.py, and what a hook may return."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Step:
    """One piece of code the benchmark has run, and what it printed."""
    code: str
    output: str


@dataclass(frozen=True)
class EpisodeStart:
    messages: list[dict]
    step_limit: int


@dataclass(frozen=True)
class BeforeModelCall:
    messages: list[dict]
    earlier_steps: tuple[Step, ...]
    steps_left: int


@dataclass(frozen=True)
class BeforeAction:
    """The model has replied; `proposed_code`, taken from `reply_text`, has not been run yet."""
    reply_text: str
    proposed_code: str
    messages: list[dict]
    earlier_steps: tuple[Step, ...]
    steps_left: int


@dataclass(frozen=True)
class AfterStep:
    """`step` has just been taken; it is not in `earlier_steps`."""
    step: Step
    reply_text: str
    messages: list[dict]
    earlier_steps: tuple[Step, ...]
    steps_left: int


@dataclass(frozen=True)
class Tips:
    """Added to the first message, after the task."""
    tips: list[str]


@dataclass(frozen=True)
class Hint:
    """`message` is added to the conversation as a user message."""
    message: str


@dataclass(frozen=True)
class Block:
    """The proposed code is not run; `message` goes to the model instead and it replies again."""
    message: str
