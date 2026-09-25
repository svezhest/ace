"""Разбор ответов модели, общий для всех уровней. Каждая функция берёт текст (или None) и не падает.

    opened(tag)         после <tag> до </tag> или конца; None без <tag> (DC: cheatsheet)
    enclosed(tag)       между <tag> и </tag> без учёта регистра; "" без пары (TF-GRPO: Experiences)
    between(text, a, b) между первым a и следующим b; "" без них (EvoLib)
    fenced(text, tag)   все блоки ```tag подряд (EvoLib)
    json_block          JSON из последнего ```json или всего текста; None, если не разбирается (TF-GRPO)
    subtasks            блоки <subtask> с description (EvoLib)
    counted_line(id)    «[id] helpful=N harmful=M :: текст» -> (текст, N, M) (ACE BulletpointAnalyzer)
    scope_*             ответы синтезатора, селектора, классификатора и оптимизатора SCOPE, с откатами апстрима"""
import json
import re


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

# SCOPE (SCOPE/scope 4dc0da5): разбор ответов дословно, с откатами апстрима


def scope_json(text):
    """GuidelineSynthesizer._extract_json: весь текст, первый блок ```{...}```, первый {...} с update_text."""
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        pass
    matches = re.findall(r'```(?:json)?\s*(\{.*?\})\s*```', text or "", re.DOTALL)
    if matches:
        try:
            return json.loads(matches[0])
        except json.JSONDecodeError:
            pass
    for match in re.findall(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', text or "", re.DOTALL):
        try:
            data = json.loads(match)
            if "update_text" in data:
                return data
        except json.JSONDecodeError:
            continue
    return None


def scope_guideline(text, quality=False):
    """Кандидат синтезатора -> dict(update_text, rationale, confidence) или None. На качестве (одна модель) текст
    правила без пробелов по краям, пустой и «no improvement needed» / «none» — None; на ошибке и у кандидатов
    Best-of-N — как есть. Не словарь — None (у апстрима падает .get)."""
    try:
        data = scope_json(text)
        if not data:
            return None
        update = data.get("update_text", "")
        if not isinstance(update, str):         # у апстрима дальше падает on_step_complete
            return None
        if quality:
            update = update.strip()
            if not update or update.lower() in ("", "no improvement needed", "none"):
                return None
        return dict(update_text=update, rationale=data.get("rationale", ""), confidence=data.get("confidence", "medium"))
    except (AttributeError, TypeError):
        return None


def scope_selection(text, n):
    """_select_best_update: номер selected_index, если он в [0, n), иначе 0; сбой разбора — 0."""
    try:
        data = scope_json(text)
        if data and "selected_index" in data:
            i = data["selected_index"]
            return i if 0 <= i < n else 0
        return 0
    except TypeError:
        return 0


def scope_fenced(text):
    """Блок ```json, иначе ```, иначе весь текст (как у классификатора и оптимизатора SCOPE)."""
    text = (text or "").strip()
    for fence in ("```json", "```"):
        if fence in text:
            start = text.find(fence) + len(fence)
            return text[start:text.find("```", start)].strip()
    return text


def scope_object(text):
    """Разбор оптимизатора SCOPE (RuleAnalyzer, слияние, поглощение, конфликт): блок, затем от первой { до
    последней }, затем одинарные кавычки -> двойные; None, если не разобралось."""
    text = scope_fenced(text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start, end = text.find("{"), text.rfind("}") + 1
    if start == -1 or end <= start:
        return None
    text = text[start:end]
    for candidate in (text, text.replace("'", '"')):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    return None


def scope_analysis(text):
    """RuleAnalyzer.analyze -> dict(consolidation, subsumption, conflicts); сбой — пустые списки."""
    data = scope_object(text)
    if not isinstance(data, dict):
        return dict(consolidation=[], subsumption=[], conflicts=[])
    for key in ("consolidation", "subsumption", "conflicts"):
        data.setdefault(key, [])
    return data


def scope_rule(text):
    """Слитое или исправленное правило -> (rule, rationale); без обоих ключей — None (KeyError апстрима)."""
    data = scope_object(text)
    try:
        return data["rule"], data["rationale"]
    except (KeyError, TypeError, IndexError):
        return None


def scope_subsumed(text):
    """_verify_subsumption: result.get("subsumed", False); сбой — False."""
    data = scope_object(text)
    return bool(data.get("subsumed", False)) if isinstance(data, dict) else False


def scope_classification(text, initial, domains):
    """_classify_and_check_duplicate: значения по умолчанию, домен не из списка у strategic -> general,
    confidence -> float; любой сбой — tactical с исходной confidence."""
    fallback = dict(is_duplicate=False, scope="tactical", confidence=initial, domain="general")
    try:
        c = json.loads(scope_fenced(text))
        c.setdefault("is_duplicate", False)
        c.setdefault("scope", "tactical")
        c.setdefault("confidence", initial)
        c.setdefault("domain", "general")
        if c["scope"] == "strategic" and c.get("domain", "general") not in domains:
            c["domain"] = "general"
        c["confidence"] = float(c["confidence"])
        return c
    except (ValueError, TypeError, AttributeError, KeyError):
        return fallback
