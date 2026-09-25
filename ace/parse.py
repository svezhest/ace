"""Разбор ответов модели, общий для всех уровней. Каждая функция берёт текст (или None) и не падает.

    opened(tag)         после <tag> до </tag> или конца; None без <tag> (DC: cheatsheet)
    enclosed(tag)       между <tag> и </tag> без учёта регистра; "" без пары (TF-GRPO: Experiences)
    between(text, a, b) между первым a и следующим b; "" без них (EvoLib)
    fenced(text, tag)   все блоки ```tag подряд (EvoLib)
    json_block          JSON из последнего ```json или всего текста; None, если не разбирается (TF-GRPO)
    subtasks            блоки <subtask> с description (EvoLib)
    counted_line(id)    «[id] helpful=N harmful=M :: текст» -> (текст, N, M) (ACE BulletpointAnalyzer)"""
import json


def opened(tag):
    def parse(text):
        if not text or f"<{tag}>" not in text:
            return None
        return text.split(f"<{tag}>", 1)[1].strip().split(f"</{tag}>")[0].strip()
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
