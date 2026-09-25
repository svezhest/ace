"""Сравнение запросов агентов MCE (Claude Agent SDK) без того, что зависит от хоста, а не от кода (DEVIATIONS
MCE7): вывод команд Bash агента и его фоновых задач (TaskOutput, TaskStop: id задачи случайный) — в результате
инструмента и в фоновом вызове CLI «Command: ...\\nOutput: ...» —
и сегодняшняя дата в описании WebSearch. Остальное, в том числе результаты Read / Write / Edit / Glob / Grep, —
побайтно. Нужна воспроизведению (tests/live/test_mce.py) и записи с кэшем (record.py --cache --normalize mce)."""
import json
import re

TODAY = re.compile(r"Today's date is \d{4}-\d\d-\d\d")
BASH = "(вывод Bash хоста)"
SHELL = ("Bash", "TaskOutput", "TaskStop", "KillShell")     # Bash и его фоновые задачи (id задачи случайный)


def normalize(c):
    """Канонический запрос -> строка сравнения."""
    body = json.loads(c)
    names = {}
    for m in body.get("messages", []):
        for call in m.get("tool_calls") or []:
            names[call["id"]] = call["function"]["name"]
        if m.get("role") == "tool" and names.get(m.get("tool_call_id")) in SHELL:
            m["content"] = BASH
        if m.get("role") == "user" and isinstance(m.get("content"), list):
            for part in m["content"]:
                text = part.get("text", "")
                if text.startswith("Command: ") and "\nOutput: " in text:
                    part["text"] = text.split("\nOutput: ", 1)[0] + "\nOutput: " + BASH
    text = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return TODAY.sub("Today's date is DATE", text)
