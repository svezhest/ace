"""Write src/*.md prompt files byte-exact from the Harness-R1 ALFWorld task source."""
import ast, sys, pathlib
task_py, src = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
tree = ast.parse(task_py.read_text())
consts = {}
for node in ast.walk(tree):
    if isinstance(node, ast.FunctionDef) and node.name == "get_task_instruction":
        consts["starting_prompt.md"] = node.body[0].value.value
    if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "no_exec_msg" and isinstance(node.value, ast.Constant):
        consts["no_tool_call.md"] = node.value.value
for node in ast.walk(tree):
    if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "ChatCompletionUserMessageParam":
        for kw in node.keywords:
            if kw.arg == "content" and isinstance(kw.value, ast.Constant) and kw.value.value.startswith("No valid tool calls"):
                consts["invalid_tool_call.md"] = kw.value.value
for name, text in consts.items():
    (src / name).write_text(text)
    print(name, len(text), repr(text[:60]))
