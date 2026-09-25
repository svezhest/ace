"""Разбор ответов модели, общий для всех уровней. Каждая функция берёт текст (или None) и не падает.

    opened(tag)         после <tag> до </tag> или конца; None без <tag> (DC: cheatsheet)
    enclosed(tag)       между <tag> и </tag> без учёта регистра; "" без пары (TF-GRPO: Experiences)
    between(text, a, b) между первым a и следующим b; "" без них (EvoLib)
    fenced(text, tag)   все закрытые блоки ```tag подряд, каждый с переводом строки (EvoLib extract_fenced_blocks)
    first_fenced        первый закрытый блок ```tag без пробелов по краям; "" без него (EvoLib extract_first_fenced_block)
    json_block          JSON из последнего ```json или всего текста; None, если не разбирается (TF-GRPO)
    subtasks            блоки <subtask> с description (EvoLib extract_subtasks)
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
        if start_tag in low and end_tag in low:
            start = low.index(start_tag) + len(start_tag)
            return text[start:low.index(end_tag, start)].strip()
        return ""
    return parse


def between(text, start, end):
    if start not in text or end not in text.split(start, 1)[1]:
        return ""
    return text.split(start, 1)[1].split(end, 1)[0].strip()


def fenced(text, tag):
    out, rest = "", text or ""
    while "```" + tag in rest:
        rest = rest.split("```" + tag, 1)[1]
        if "```" not in rest:
            break
        block, rest = rest.split("```", 1)
        out += block + "\n"
    return out


def first_fenced(text, tag):
    rest = (text or "").split("```" + tag, 1)
    return rest[1].split("```", 1)[0].strip() if len(rest) == 2 and "```" in rest[1] else ""


def json_block(text):
    try:
        return json.loads(text.split("```json")[-1].split("```")[0])
    except (json.JSONDecodeError, AttributeError):
        return None


def subtasks(text):
    """Пары (блок <subtask>...</subtask> целиком, его первый <description>...</description> вместе с тегами), как
    extract_subtasks апстрима: блок кончается на первом </subtask>; блок без description — пусто целиком."""
    out, rest = [], text or ""
    while "<subtask>" in rest:
        rest = rest.split("<subtask>", 1)[1]
        if "</subtask>" not in rest:
            break
        block, rest = rest.split("</subtask>", 1)
        if "<description>" not in block or "</description>" not in block.split("<description>", 1)[1]:
            return []
        description = block.split("<description>", 1)[1].split("</description>", 1)[0]
        out.append((f"<subtask>{block}</subtask>", f"<description>{description}</description>"))
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
