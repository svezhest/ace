"""Разбор ответов модели, общий для всех уровней. Каждая функция берёт текст (или None) и не падает.

    opened(tag)         после первого <tag> до </tag>, следующего <tag> или конца; None без <tag>
                        (DC: extract_cheatsheet апстрима)
    enclosed(tag)       между <tag> и </tag> без учёта регистра; "" без пары (TF-GRPO: Experiences)
    between(text, a, b) между первым a и следующим b; "" без них (EvoLib)
    fenced(text, tag)   все блоки ```tag подряд (EvoLib)
    json_block          JSON из последнего ```json или всего текста; None, если не разбирается (TF-GRPO)
    subtasks            блоки <subtask> с description (EvoLib)
    counted_line(id)    «[id] helpful=N harmful=M :: текст» -> (текст, N, M) (ACE BulletpointAnalyzer)
    ace_json            extract_json_from_text ACE: весь текст, ```json, первый объект {...} (ACE)
    bullet_tags         _extract_bullet_tags рефлектора ACE без json_mode: массив после "bullet_tags" (ACE)
    ace_operations      _extract_and_validate_operations куратора ACE: операции или None (ACE)"""
import json
import re


def opened(tag):
    def parse(text):
        if not text or f"<{tag}>" not in text:
            return None
        return text.split(f"<{tag}>")[1].strip().split(f"</{tag}>")[0].strip()
    return parse


def enclosed(tag):
    start_tag, end_tag = f"<{tag.lower()}>", f"</{tag.lower()}>"

    def parse(text):
        if text is None:
            return None
        low = text.lower()
        start = low.find(start_tag)
        end = low.find(end_tag, start + len(start_tag)) if start >= 0 else -1
        return text[start + len(start_tag):end].strip() if end >= 0 else ""
    return parse


def between(text, start, end):
    if start not in text or end not in text.split(start, 1)[1]:
        return ""
    return text.split(start, 1)[1].split(end, 1)[0].strip()


def fenced(text, tag):
    return "\n".join(part.split("```")[0] for part in (text or "").split("```" + tag)[1:])


def json_block(text):
    try:
        return json.loads(text.split("```json")[-1].split("```")[0])
    except (json.JSONDecodeError, AttributeError):
        return None


def subtasks(text):
    """Пары (блок <subtask> целиком, его description); без description извлечение не удаётся целиком."""
    out = []
    for chunk in text.split("<subtask>")[1:]:
        if "</subtask>" not in chunk:
            continue
        block = chunk.split("</subtask>")[0]
        if not between(block, "<description>", "</description>"):
            return []
        out.append((f"<subtask>{block}</subtask>", between(block, "<description>", "</description>")))
    return out


def counted_line(id):
    def parse(text):
        text = (text or "").strip()
        if not (text.startswith(f"[{id}]") and "::" in text):
            return None
        counts, body = text.split("]", 1)[1].split("::", 1)
        counts = dict(kv.split("=", 1) for kv in counts.split() if "=" in kv)
        if not (counts.get("helpful", "").isdigit() and counts.get("harmful", "").isdigit()):
            return None
        return body.strip(), int(counts["helpful"]), int(counts["harmful"])
    return parse


def ace_json(text):
    """extract_json_from_text (ACE playbook_utils.py:256): весь текст; иначе первый разобранный блок ```json (регистр
    не важен); иначе первый разобранный объект {...} по балансу скобок, скобки в строках не считаются; иначе None."""
    try:
        try:
            return json.loads(text.strip())
        except json.JSONDecodeError:
            pass
        for block in re.findall(r"```json\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE):
            try:
                return json.loads(block.strip())
            except json.JSONDecodeError:
                continue
        for candidate in braced(text):
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                continue
    except Exception:
        pass
    return None


def braced(text):
    """Объекты {...} верхнего уровня по балансу скобок, как find_json_objects апстрима (кавычки пропускаются
    целиком, экранированный символ тоже)."""
    out, i = [], 0
    while i < len(text):
        if text[i] != "{":
            i += 1
            continue
        depth, start = 1, i
        i += 1
        while i < len(text) and depth > 0:
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
            elif text[i] == '"':
                i += 1
                while i < len(text) and text[i] != '"':
                    if text[i] == "\\":
                        i += 1
                    i += 1
            i += 1
        if depth == 0:
            out.append(text[start:i])
    return out


def bullet_tags(text):
    """_extract_bullet_tags рефлектора ACE без json_mode (reflector.py:100): JSON-массив от первой [ после
    "bullet_tags" до парной ]; иначе []. Что внутри массива — как есть."""
    start = (text or "").find('"bullet_tags"')
    bracket = text.find("[", start) if start != -1 else -1
    if bracket == -1:
        return []
    depth, end = 0, bracket
    for i in range(bracket, len(text)):
        if text[i] == "[":
            depth += 1
        elif text[i] == "]":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    try:
        return json.loads(text[bracket:end])
    except json.JSONDecodeError:
        return []


def ace_operations(text):
    """_extract_and_validate_operations куратора ACE (curator.py:344): JSON с reasoning (строка) и operations
    (список словарей с type, у ADD ещё section и content) -> список операций; иначе None — ответ куратора
    пропускается целиком."""
    info = ace_json(text or "")
    try:
        if not info or "reasoning" not in info or "operations" not in info:
            return None
        if not isinstance(info["reasoning"], str) or not isinstance(info["operations"], list):
            return None
        for op in info["operations"]:
            if not isinstance(op, dict) or "type" not in op:
                return None
            if op["type"] == "ADD" and not {"type", "section", "content"} <= set(op):
                return None
    except TypeError:
        return None
    return info["operations"]
