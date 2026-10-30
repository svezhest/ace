"""Заглушка модели для editor.py: проверка edit/propose/finish, песочницы и того, что вид не меняется. Без LLM."""
import json, os, sys
sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import editor as E

def resp(*calls, content=""):
    return {"choices": [{"message": {"content": content, "tool_calls": [
        {"id": f"c{i}", "function": {"name": n, "arguments": json.dumps(a)}} for i, (n, a) in enumerate(calls)]},
        "finish_reason": "tool_calls"}], "usage": {"prompt_tokens": 1000, "completion_tokens": 10}}

def run(script, role, bench="alf", n_obs=3):
    it = iter(script)
    E.F.chat = lambda *a, **k: (next(it), None)
    E.F.MAX_GEN, E.F.TEMP, E.F.URL = 4096, 0.6, "mock:"   # заглушка модели: профиль стенда не нужен
    root = E.build_work(bench, "mock_" + role)
    prof = E.make_profile(root, "mock_" + role)
    end, st, items = E.run_session(role, "sys", "first", root, prof, 1, f"{HERE}/logs/mock_{role}.jsonl", n_obs)
    return root, end, st, items, [json.loads(l) for l in open(f"{HERE}/logs/mock_{role}.jsonl")]

before = E.tree_hash(E.VIEWS["alf"] + "/src")
H = "src/harness.py"
script = [
    resp(("bash", {"command": "grep -n MAX_STEPS src/harness.py"})),
    resp(("bash", {"command": "echo hi > src/x"})),                                      # запись — отказ
    resp(("edit", {"path": H, "old_string": "MAX_STEPS = 51", "new_string": "x"})),      # не найдено
    resp(("edit", {"path": H, "old_string": "return None", "new_string": "return 0"})),  # несколько
    resp(("edit", {"path": "src/bridge.py", "old_string": "import", "new_string": "x"})),
    resp(("edit", {"path": "README.md", "old_string": "#", "new_string": "x"})),
    resp(("edit", {"path": "../alfworld/view/src/harness.py", "old_string": "M", "new_string": "x"})),
    resp(("edit", {"path": H, "old_string": "MAX_STEPS = 50", "new_string": "MAX_STEPS = (50"})),   # синтаксис
    resp(("edit", {"path": H, "old_string": "MAX_STEPS = 50", "new_string": "MAX_STEPS = 50"})),    # то же
    resp(("edit", {"path": "./src/hooks.py", "old_string": "", "new_string": "def on_init(ctx, nb):\n    return None\n"}),
         ("edit", {"path": "src/hooks.py", "old_string": "", "new_string": "x = 1\n"})),             # второй — файл не пуст
    resp(("bash", {"command": "grep -n MAX_STEPS src/harness.py"})),                     # повтор после правки разрешён
    resp(("edit", {"path": "src/new_tips.md", "old_string": "", "new_string": "tip\n"})),
    resp(("edit", {"path": H, "old_string": "MAX_STEPS = 50\n", "new_string": "MAX_STEPS = 50  # limit\n"})),
    resp(("edit", {"path": "src/extra.py", "old_string": "", "new_string": "def f():\n    return undefined_name\n"})),
    resp(("finish", {})),                                                                 # pyflakes: undefined name
    resp(("finish", {})),
]
root, end, st, items, log = run(script, "editor")
fin = [r["shown"] for t in log if t.get("type") == "turn" for r in t["results"] if r["name"] == "finish"]
assert len(fin) == 2 and "Not finished yet" in fin[0] and "undefined name" in fin[0] and fin[1] == "Finished.", fin
assert end == "finish", end
assert st["edits_applied"] == 4 and st["edits_attempted"] == 12, st
assert st["edit_fail"] == {"not_found": 1, "multiple": 1, "bridge": 1, "path": 2, "syntax": 1, "same": 1, "empty_old": 1}, st["edit_fail"]
assert open(f"{root}/src/hooks.py").read().startswith("def on_init")
assert "# limit" in open(f"{root}/src/harness.py").read()
assert os.path.exists(f"{root}/src/new_tips.md")
assert E.tree_hash(E.VIEWS["alf"] + "/src") == before
shown = [r["shown"] for t in log if t.get("type") == "turn" for r in t["results"]]
assert "read-only" in shown[1] or "Error" in shown[1], shown[1]
assert "same command" not in shown[10], shown[10]
for s in shown[2:13]:
    print("---", s[:300])
d = E.diff_src("alf", root)
print(d)

# предложения и финал по лимиту bash
E.BASH_LIMIT = 2
script = [resp(("bash", {"command": "ls src"})), resp(("bash", {"command": "ls"})),
          resp(("bash", {"command": "ls -la"}), ("propose", {"problem": "p", "fix": "f", "observations": [1, 9]}),
               ("propose", {"problem": "p", "fix": "f", "observations": [2]})),
          resp(("finish", {}))]
root, end, st, items, log = run(script, "proposer")
assert end == "finish" and st["proposals"] == 1 and st["proposals_rejected"] == 1, (end, st)
notes = [t["text"] for t in log if t.get("type") == "note"]
assert any("bash calls" in n for n in notes), notes
print(notes, [r["shown"][:80] for t in log if t.get("type") == "turn" for r in t["results"]])
print("OK")
