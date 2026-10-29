import json, sys, time, requests
url = sys.argv[1]
tools = [{"type": "function", "function": {"name": "take_action", "description": "Take an action.",
          "parameters": {"type": "object", "properties": {"action": {"type": "string", "description": "The action you would like to take"}}, "required": ["action"], "additionalProperties": False}}}]
body = {"model": "ornith15-9b", "max_tokens": 200, "temperature": 0.0, "tools": tools,
        "messages": [{"role": "system", "content": "You act in a house. Always call the tool."},
                     {"role": "user", "content": "Here is your task. You are in a room. Your task is to: look around. AVAILABLE ACTIONS: look\ninventory\n"}]}
t = time.time(); r = requests.post(url + "/chat/completions", json=body, timeout=300)
print(r.status_code, round(time.time() - t, 1)); d = r.json()
print(json.dumps(d["choices"][0], ensure_ascii=False)[:800]); print(d.get("usage"))
