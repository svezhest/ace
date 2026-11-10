"""Схемы инструментов писателя: bash, edit, finish. В финальных ходах — без bash (TOOLS[1:])."""

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
FINISH_SCHEMA = {"type": "function", "function": {
    "name": "finish", "description": "End the session.", "parameters": {"type": "object", "properties": {}}}}

TOOLS = [BASH_SCHEMA, EDIT_SCHEMA, FINISH_SCHEMA]
