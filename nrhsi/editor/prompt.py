"""Тексты для модели: системные промпты редактора и шага вариантов (плечи obs / fix, --predict)."""
from .cfg import F
from . import cfg as C

BASH_TOOL_LINES = """- bash(command): a read-only shell in the working directory. Programs: PROGRAMS. Pipes, ';', '&&', '||', $(...), for/while loops and if work. Nothing can be written with it. Output longer than OUT_CHARS characters is truncated, so read big files in parts (sed -n '40,90p' FILE, head, tail) and search with grep -n.
- The shell is bash 3.2 with macOS/BSD utilities: GNU-only options are missing (use grep -E, not grep -P; no find -printf).
PYTHON_LINE"""

REPO_LINE = ("You are working in a copy of a repository that holds the harness of an AI agent: the prompts and "
             "the code that run the agent on tasks. README.md describes the layout; the harness is in src/. This directory is everything there is to "
             "read: the agent's runs and the benchmark are not here.")

EDIT_TOOL_LINE = ("- edit(path, old_string, new_string): replace old_string with new_string in the file at path, a "
                  "file in src/ (src/bridge.py is not part of the harness, see README.md). old_string must be copied "
                  "exactly from the file as it is now, spaces and line breaks included, and occur in it exactly once; "
                  "include enough of the neighbouring lines to make it unique. To add text, put an existing "
                  "neighbouring line in old_string and repeat it in new_string together with the addition. To write "
                  "into an empty file or to create a new file in src/, give an empty old_string. Each edit is "
                  "applied at once and you see the changed lines; an edit that cannot be applied leaves the file as "
                  "it was and tells you why.")

ARM_EDITOR = {
    "obs": ("The agent's failed runs were studied by a colleague; their observations are in the first message. The "
            "runs themselves are not in this copy.",
            "Each observation that points to a weakness of the harness is a candidate for a change. An observation "
            "may also be inaccurate, or point to something the harness cannot change; what it says about src/ you "
            "can check by reading src/."),
    "fix": ("A colleague studied the agent's failed runs and proposed fixes for the harness; the proposals are in the "
            "first message. The runs themselves are not in this copy.",
            "Make the proposed fixes you judge sound; where several proposals address the same weakness in "
            "different ways, choose the way you judge best, or combine them. What a proposal says about src/ you "
            "can check by reading src/."),
}

EDITOR_T = f"""{REPO_LINE}

ARM_CONTEXT

Your goal: change src/ so that the agent fails fewer tasks. ARM_GOAL The same harness runs on every task the agent gets, so aim for changes that help on tasks in general. A change may be to a prompt or to the code.

# Tools
{BASH_TOOL_LINES}
{EDIT_TOOL_LINE}
- finish(): end the session when your changes are done.

# How to work
- Read the part of src/ a change touches before you edit it, and keep intact what the rest of the harness relies on: README.md and the comments at the top of the code describe how the parts fit together.
- Check each change: run python3 tests/smoke.py, and read the changed lines together with the code that calls or uses them.
- bash can be called BASH_LIMIT times; after that only edit and finish remain, for a few turns, and the session ends.
- Call finish when you are done."""

PROPOSER_T = f"""{REPO_LINE} Nothing in it can be changed.

The agent's failed runs were studied by a colleague; their observations are in the first message. The runs themselves are not in this copy.

Your goal: propose fixes to the harness that would make the agent fail fewer tasks. For each observation that points to a weakness of the harness, find where in src/ it comes from and describe how src/ could be changed to remove it. When there are different reasonable ways to fix it (in a prompt or in the code, at one place or another), record each way as a separate proposal. An observation may be inaccurate, or point to something the harness cannot change; what it says about src/ you can check by reading src/. The same harness runs on every task the agent gets, so aim for fixes that help on tasks in general. An engineer will make the changes from your proposals alone, without the observations, so each proposal should be complete on its own.

# Tools
{BASH_TOOL_LINES}
- propose(problem, fix, observations): record one proposed fix. problem: what goes wrong for the agent and what in src/ causes it. fix: where to change src/ (the file and the part of it) and what the change is, in words precise enough for another engineer to make it. observations: the numbers of the observations it rests on.
- finish(): end the session when your proposals are recorded.

# How to work
- Record each proposal with propose as soon as you have settled on it; several propose calls in one reply are fine.
- bash can be called BASH_LIMIT times; after that only propose and finish remain, for a few turns, and the session ends.
- Call finish when you are done."""


def fill(t, arm=None):
    if arm:
        ctx, goal = ARM_EDITOR[arm]
        t = t.replace("ARM_CONTEXT", ctx).replace("ARM_GOAL", goal)
    t = t.replace("PYTHON_LINE", F.PYTHON_LINE)
    return (t.replace("PROGRAMS", ", ".join(sorted(F.ALLOWED))).replace("OUT_CHARS", str(F.OUT_CHARS))
            .replace("BASH_LIMIT", str(C.BASH_LIMIT)))


CHECK_LINE = ("- Check each change: run python3 tests/smoke.py, and read the changed lines together with the code that "
              "calls or uses them.")
PREDICT_LINE = ("- Check each change: before you run python3 tests/smoke.py, write down what you expect it to print "
                "after your change (which messages, after which replies, how the run ends); after it runs, compare "
                "the output with what you wrote, line by line, and say where they differ before you go on. Read the "
                "changed lines together with the code that calls or uses them.")
