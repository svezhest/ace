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


def role_tools(role):
    """Набор инструментов роли (editor | proposer); в финальных ходах — без bash, [1:]."""
    return [BASH_SCHEMA, EDIT_SCHEMA if role == "editor" else PROPOSE_SCHEMA, FINISH_SCHEMA]
