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
    "merge": ("Two versions of this harness, a and b, were made independently from the same original version, each to "
              "make the agent fail fewer tasks. src/ here is the two merged line by line; their changes against the "
              "original, and the files where both changed the same lines, are in the first message.",
              "Keep what each version adds: resolve every conflict, and where a and b do the same thing in different "
              "ways or get in each other's way, keep one way that works."),
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
            .replace("BASH_LIMIT", str(C.BASH_LIMIT)).replace("FINAL_TURNS", str(C.FINAL_TURNS)))


RERUN_REPO = ("the agent's runs and the benchmark are not here.", "the agent's recorded runs are in logs/; the benchmark is not here.")
RERUN_ARM = ("The runs themselves are not in this copy.",
             "The runs are in logs/: trust your colleague initially; if you are confused, you may check the logs.")
RERUN_CHECK_LINE = ("- Check each change: run python3 tests/smoke.py and python3 tests/rerun.py (see README.md), and read "
                    "the changed lines together with the code that calls or uses them. If python3 tests/rerun.py shows "
                    "no changes in the runs an observation is about, your change may have missed.")
RERUN_AT_LINE = (" To see the values your code gets at a step of a real run, run python3 tests/rerun.py N --at K "
                 "(see README.md).")
FINISH_LINE = "- finish(): end the session when your changes are done."
FINISH_REVIEW_LINE = ("- finish(submit): hand in your changes and end the session. Before they are handed in, you see "
                      "all your changes and what python3 tests/rerun.py prints on them; then call finish again to hand "
                      "them in, change them with edit, or call finish with submit=false to hand in nothing (src/ goes "
                      "back to how it was at the start).")
CHECK_LINE = ("- Check each change: run python3 tests/smoke.py, and read the changed lines together with the code that "
              "calls or uses them.")
LIMIT_LINE = "- bash can be called BASH_LIMIT times; after that only edit and finish remain, for a few turns, and the session ends."
CLEAN_LIMIT_LINE = ("- bash can be called BASH_LIMIT times; after that FINAL_TURNS turns remain without bash: edits are still "
                    "applied and checked after each one, and then the session ends.")
CHECKED_LIMIT_LINE = ("- bash can be called BASH_LIMIT times; after that edits can no longer be checked and are not applied: "
                      "only finish remains, and the session ends.")
PREDICT_LINE = ("- Check each change: before you run python3 tests/smoke.py, write down what you expect it to print "
                "after your change (which messages, after which replies, how the run ends); after it runs, compare "
                "the output with what you wrote, line by line, and say where they differ before you go on. Read the "
                "changed lines together with the code that calls or uses them.")

# 4.11, автор: этапы, проверки в правке, rerun с ожиданием, scratch/
STAGES_LINE = ("- bash: the first STAGE_R calls are for reading. Your first edit starts the check part: from then on you "
               "have STAGE_K more bash calls to check your edits (if the STAGE_R calls run out before you edit, the check "
               "part starts then). After the check part, edits can no longer be checked and are not applied: only "
               "finish remains, and the session ends.")
INTENT_LINE = (" With each edit say what you expect it to do: expect_runs, the numbers of the recorded runs in logs/ "
               "whose course it changes ([] if none), and expect, what the harness will do differently in them. The "
               "checks after the edit compare this with the runs that did change.")
INTENT_OPT_LINE = (" With an edit you may say what you expect it to do: expect_runs, the numbers of the recorded runs in "
                   "logs/ whose course it changes, and expect, what the harness will do differently in them; the checks "
                   "after the edit then compare this with the runs that did change.")
CHECK_AUTO_ONLY_LINE = ("- Checks run by themselves: after each edit that is applied, pyflakes, python3 tests/smoke.py and "
                        "python3 tests/rerun.py are run on src/, and their output comes with the edit's answer; this uses no "
                        "bash calls. Read the changed lines together with the code that calls or uses them. To look at one "
                        "run in detail, run python3 tests/rerun.py N yourself (see README.md). If the runs an observation is "
                        "about show no changes, your change may have missed.")
AUTO_CHECK_LINE = (" After each edit that is applied, pyflakes, python3 tests/smoke.py and RERUN_NAME are run on src/; "
                   "their output comes with the edit's answer and uses no bash calls.")
RERUN_TOOL_LINE = ("- rerun(expect_diff, run): replays the runs in logs/ on the current src/ (see README.md). "
                   "expect_diff is what you expect it to show: none (the runs go as in the log), prompt (you changed "
                   "the prompt) or control (you changed the harness code, so the runs go differently from some point). "
                   "It answers ok or failed (did the runs go as you expected), then what changed; run: one run in "
                   "detail.")
RERUN_TOOL_CHECK_LINE = ("- Check each change: run python3 tests/smoke.py and the rerun tool (see README.md), and read the "
                         "changed lines together with the code that calls or uses them. If rerun shows no changes in "
                         "the runs an observation is about, your change may have missed.")
SCRATCH_NOWRITE = "Nothing can be written with it."
SCRATCH_WRITE = ("Files can be written only in scratch/ (empty at the start; > scratch/NAME, or from python3); "
                 "everything else is read-only, and there is no /tmp.")


# 5.11 --navigator: пример прицельного поиска (выдуманный репозиторий), без пояснений
NAV_EXAMPLE = """# Example: finding what a change needs (another repository)
Observation: "Exported reports lose their last row: write_rows() (src/export.py:40-52) stops one row early."

bash(command="grep -n 'write_rows\\|n_rows' src/*.py")
src/export.py:18:def n_rows(table):
src/export.py:40:def write_rows(out, table):
src/report.py:63:    write_rows(f, table)

bash(command="sed -n '36,56p' src/export.py")
def write_rows(out, table):
    for i in range(n_rows(table) - 1):
    ...

bash(command="sed -n '16,24p' src/export.py")
...

bash(command="sed -n '55,70p' src/report.py")
...

bash(command="grep -n 'rows' logs/run_4.jsonl | cut -c1-200 | head -5")
..."""


# 5.11 --navigator 2: тот же выдуманный репозиторий, но поиск начинается с места из наблюдения
NAV_EXAMPLE2 = """# Example: finding what a change needs (another repository)
Observation: "Exported reports lose their last row: write_rows() (src/export.py:40-52) stops one row early."

bash(command="sed -n '36,56p' src/export.py")
def write_rows(out, table):
    for i in range(n_rows(table) - 1):
    ...

bash(command="grep -n 'n_rows\\|write_rows(' src/*.py")
src/export.py:18:def n_rows(table):
src/export.py:40:def write_rows(out, table):
src/report.py:63:    write_rows(f, table)

bash(command="sed -n '16,24p' src/export.py")
..."""

# 5.11 --plan-line: планирование тикета в ответе модели (не отдельный шаг)
PLAN_LINE = ("- Before an edit, write in your reply how the run the observation is about will go once the edit is in: "
             "at which step the harness acts differently, and what the agent then sees and does. Then make the edit "
             "that does that.")

# 5.11 --broad-example: правка, которая делает больше задуманного (выдуманный репозиторий), без пояснений
BROAD_EXAMPLE = """# Example: an edit that changes more than the run it is for (another repository)
Observation: "Run 7 shows a stale price: get_price() (src/cache.py:20-31) returns the cached value without checking its age."

edit(path="src/cache.py", old_string="    return CACHE[item]", new_string="    return fetch(item)")
python3 tests/rerun.py prints:
runs 2, 5, 7, 9 (1 failed, 3 passed): diverges at model call 3: what the model sees differs from the log
runs 1, 3, 4, 6, 8 (2 failed, 3 passed): no changes (same as the log to the end)

edit(path="src/cache.py", old_string="    return fetch(item)", new_string="    if time.time() - STAMP[item] > MAX_AGE:\n        return fetch(item)\n    return CACHE[item]")
python3 tests/rerun.py prints:
run 7 (failed): diverges at model call 3: what the model sees differs from the log
runs 1, 2, 3, 4, 5, 6, 8, 9 (2 failed, 6 passed): no changes (same as the log to the end)"""
