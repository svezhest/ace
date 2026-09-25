"""Эталоны апстримов (bridge/fixtures, снятые bridge/capture_*.py) и записи DEVIATIONS.md, по которым тест
нормализует расхождение. Сам апстрим тестам не нужен."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "bridge" / "fixtures"
ENTRY = re.compile(r"^\s*([A-Z]+\d+)\. \*\*", re.M)


def fixture(method, level):
    return json.loads((FIXTURES / method / f"{level}.json").read_text())["data"]


def entries():
    return ENTRY.findall((ROOT / "DEVIATIONS.md").read_text())


def deviation(*ids):
    """Отметка у нормализации: расхождение записано в DEVIATIONS.md под этим идентификатором."""
    lack = [i for i in ids if i not in entries()]
    assert not lack, f"нет в DEVIATIONS.md: {', '.join(lack)}"


def messages(call):
    """Системный и пользовательский промпт записанного фейком запроса ("" — если сообщения нет)."""
    by_role = {m["role"]: m["content"] for m in call["messages"]}
    return by_role.get("system", ""), by_role.get("user", "")
