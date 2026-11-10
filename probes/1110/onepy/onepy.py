"""Один Python: что говорит каждая проверка на правку с синтаксисом, которого нет в Python песочницы (3.9).
python3 probes/1110/onepy/onepy.py HOME   (модель не вызывается; проигрыш одной выдуманной сессии через editor/replay.py)
Две правки src/hooks.py на входе 08: (a) оператор match; (b) аннотация `Hint | None` без __future__.
"""
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
OLD = "def on_post_step(now: AfterStep, memory: dict) -> Optional[Hint]:\n    return None"
EDITS = {
    "match": "def on_post_step(now: AfterStep, memory: dict) -> Optional[Hint]:\n    match now.action:\n"
             "        case \"look\":\n            return None\n    return None",
    "union": "def on_post_step(now: AfterStep, memory: dict) -> Hint | None:\n    return None",
}
home = sys.argv[1]
os.makedirs(home, exist_ok=True)
for name, new in EDITS.items():
    log = f"{home}/{name}.in.jsonl"
    call = {"name": "edit", "arguments": json.dumps({"path": "src/hooks.py", "old_string": OLD, "new_string": new})}
    with open(log, "w") as f:
        f.write(json.dumps({"type": "turn", "tool_calls": [call], "content": None, "usage": {}, "finish_reason": "tool_calls"}) + "\n")
        f.write(json.dumps({"type": "turn", "tool_calls": [{"name": "finish", "arguments": "{}"}], "content": None,
                            "usage": {}, "finish_reason": "tool_calls"}) + "\n")
    subprocess.run([sys.executable, f"{ROOT}/editor/replay.py", log, "--", "--bench", "alf",
                    "--view", f"{ROOT}/runs/typed_1110/alf_r1", "--input-text", f"{ROOT}/runs/typed_1110/in/08_v_rr.txt",
                    "--ticket", f"{ROOT}/docs/tickets_1106k/08.json", "--lint", f"{ROOT}/editor/lint",
                    "--tag", name, "--home", home], check=True, capture_output=True)
    for r in map(json.loads, open(f"{home}/logs/{name}.jsonl")):
        if r.get("type") == "turn":
            for c, res in zip(r["tool_calls"], r["results"]):
                print(f"===== {name}: {c['name']}\n{res['shown']}\n")
