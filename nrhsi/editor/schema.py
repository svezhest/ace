"""Схемы инструментов: bash, edit (редактор), propose (шаг вариантов), finish."""


BASH_SCHEMA = {"type": "function", "function": {
    "name": "bash", "description": "Run a read-only shell command in the working directory. Pipes, ';', '&&', '||', "
    "$(...), for/while loops and if work; nothing can be written. Long output is truncated: use grep -n, sed -n 'a,bp', head, tail.",
    "parameters": {"type": "object", "properties": {"command": {"type": "string", "description": "The command line"}},
                   "required": ["command"]}}}
EDIT_SCHEMA = {"type": "function", "function": {
    "name": "edit", "description": "Replace old_string with new_string in a file in src/. old_string must match the "
    "file's current text exactly (spaces, line breaks) and occur in it exactly once; an empty old_string writes into "
    "an empty file or creates a new one.",
    "parameters": {"type": "object", "properties": {
        "path": {"type": "string", "description": "The file to change, e.g. src/FILE"},
        "old_string": {"type": "string", "description": "Exact text from the file to replace"},
        "new_string": {"type": "string", "description": "The text to put in its place"}},
        "required": ["path", "old_string", "new_string"]}}}
PROPOSE_SCHEMA = {"type": "function", "function": {
    "name": "propose", "description": "Record one proposed fix to the harness.",
    "parameters": {"type": "object", "properties": {
        "problem": {"type": "string", "description": "What goes wrong for the agent and what in src/ causes it"},
        "fix": {"type": "string", "description": "Where to change src/ and what the change is, in words"},
        "observations": {"type": "array", "items": {"type": "integer"},
                         "description": "Numbers of the observations this rests on"}},
        "required": ["problem", "fix", "observations"]}}}
FINISH_SCHEMA = {"type": "function", "function": {
    "name": "finish", "description": "End the session.", "parameters": {"type": "object", "properties": {}}}}


FINISH_SUBMIT_SCHEMA = {"type": "function", "function": {
    "name": "finish", "description": "Hand in your changes and end the session; submit=false hands in nothing.",
    "parameters": {"type": "object", "properties": {
        "submit": {"type": "boolean", "description": "false: drop all your changes, src/ goes back to how it was at "
                   "the start, and nothing is handed in. Default true."}}}}}


RERUN_SCHEMA = {"type": "function", "function": {
    "name": "rerun", "description": "Replay the runs in logs/ on the current src/ (see README.md) and say whether they "
    "went as you expected.",
    "parameters": {"type": "object", "properties": {
        "expect_diff": {"type": "string", "enum": ["none", "prompt", "control"], "description":
                        "What you expect the replay to show on the current src/. none: the runs go exactly as in the "
                        "log (src/ as at the start, or a change that should not touch these runs). prompt: you changed "
                        "the prompt, so the runs differ from the log at the prompt and nothing after it is compared. "
                        "control: you changed the harness code, so from some point on the runs go differently from "
                        "the log."},
        "run": {"type": "integer", "description": "One run, shown in detail. Without it: all runs, one line per group "
                "of runs that behave the same way."}},
        "required": ["expect_diff"]}}}


def bash_schema():
    """--scratch: в описании bash — запись только в scratch/."""
    from . import cfg as C
    if not C.SCRATCH:
        return BASH_SCHEMA
    f = dict(BASH_SCHEMA["function"])
    f["description"] = f["description"].replace("Run a read-only shell", "Run a shell").replace(
        "nothing can be written", "only scratch/ can be written")
    assert f["description"] != BASH_SCHEMA["function"]["description"]
    return {"type": "function", "function": f}


def role_tools(role):
    """Набор инструментов роли (editor | proposer); в финальных ходах — без bash, [1:]."""
    from . import cfg as C
    fin = FINISH_SUBMIT_SCHEMA if role == "editor" and C.FINISH_REVIEW else FINISH_SCHEMA
    rr = [RERUN_SCHEMA] if role == "editor" and C.RERUN_TOOL else []
    return [bash_schema(), EDIT_SCHEMA if role == "editor" else PROPOSE_SCHEMA] + rr + [fin]
