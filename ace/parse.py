"""Разбор ответов модели, общий для всех уровней. Каждая функция берёт текст (или None) и не падает. Разборщики
апстримов — порты их функций (имя и файл — в докстроке), с их откатами; свои промпты стенда со схемой ответа на
проводе разбирает json_object / structured."""
import json
import re

from . import prompts


def opened(tag):
    """После первого <tag> до </tag>, следующего <tag> или конца; None без <tag> (DC: extract_cheatsheet апстрима)."""
    def parse(text):
        if not text or f"<{tag}>" not in text:
            return None
        return text.split(f"<{tag}>")[1].strip().split(f"</{tag}>")[0].strip()
    return parse


def enclosed(tag):
    """Между <tag> и </tag> без учёта регистра; "" без пары (TF-GRPO: <Experiences>)."""
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
    """Между первым start и следующим end; "" без них (EvoLib)."""
    if start not in text or end not in text.split(start, 1)[1]:
        return ""
    return text.split(start, 1)[1].split(end, 1)[0].strip()


def fenced(text, tag):
    """Все закрытые блоки ```tag подряд, каждый с переводом строки (EvoLib: extract_fenced_blocks)."""
    out, rest = "", text or ""
    while "```" + tag in rest:
        rest = rest.split("```" + tag, 1)[1]
        if "```" not in rest:
            break
        block, rest = rest.split("```", 1)
        out += block + "\n"
    return out


def first_fenced(text, tag):
    """Первый закрытый блок ```tag без пробелов по краям; "" без него (EvoLib: extract_first_fenced_block)."""
    parts = (text or "").split("```" + tag, 1)
    if len(parts) < 2 or "```" not in parts[1]:
        return ""
    return parts[1].split("```", 1)[0].strip()


def json_block(text):
    """JSON из последнего ```json или всего текста; None, если не разбирается (TF-GRPO)."""
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
    """«[id] helpful=N harmful=M :: текст» -> (текст, N, M); иначе None (ACE: BulletpointAnalyzer)."""
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


def first_json(candidates, accept=None):
    """Первый кандидат, который разбирается как JSON (и проходит accept); иначе None."""
    for text in candidates:
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            continue
        if accept is None or accept(data):
            return data
    return None


def ace_json(text):
    """extract_json_from_text (ACE playbook_utils.py:256): весь текст; иначе первый разобранный блок ```json (регистр
    не важен); иначе первый разобранный объект {...} по балансу скобок, скобки в строках не считаются; иначе None."""
    try:
        try:
            return json.loads(text.strip())
        except json.JSONDecodeError:
            pass
        blocks = [b.strip() for b in re.findall(r"```json\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)]
        return first_json(blocks + braced(text))
    except Exception:
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


def matching(text, start, pair):
    """Номер скобки, парной к открывающей pair[0] на start (скобки внутри строк считаются); нет пары — None."""
    opening, closing = pair
    depth = 0
    for i in range(start, len(text)):
        if text[i] == opening:
            depth += 1
        elif text[i] == closing:
            depth -= 1
            if depth == 0:
                return i
    return None


def bullet_tags(text):
    """_extract_bullet_tags рефлектора ACE без json_mode (reflector.py:100): JSON-массив от первой [ после
    "bullet_tags" до парной ]; иначе []. Что внутри массива — как есть."""
    start = (text or "").find('"bullet_tags"')
    bracket = text.find("[", start) if start != -1 else -1
    if bracket == -1:
        return []
    end = matching(text, bracket, "[]")
    if end is None:
        return []
    try:
        return json.loads(text[bracket:end + 1])
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


def bullet_ids(text):
    """_extract_bullet_ids_regex генератора ACE (generator.py:115): id в квадратных скобках по всему ответу."""
    return re.findall(r"\[([a-z]{3,}-\d{5})\]", text or "")


NO_ANSWER = prompts.text("no_answer")


def ace_answer(text):
    """extract_answer ACE (utils.py:100): весь ответ JSON-объект -> str(final_answer); иначе по очереди последний
    Finish[...], "final_answer": "..." в двойных, в одинарных кавычках и без кавычек, «the final answer is» с
    \\boxed{...} и без него; иначе NO_ANSWER."""
    text = text or ""
    try:
        return str(json.loads(text).get("final_answer", NO_ANSWER))
    except (json.JSONDecodeError, KeyError, AttributeError):
        pass
    for pattern in (r"Finish\[(.*?)\]", r'"final_answer"\s*:\s*"([^"]*)"', r"'final_answer'\s*:\s*'([^']*)'"):
        found = re.findall(pattern, text)
        if found:
            return found[-1]
    found = re.findall(r'[\'"]final_answer[\'"]\s*:\s*([^,}]+)', text)
    if found:
        return re.sub(r"[,}]*$", "", found[-1].strip())
    start = re.search(r"[Tt]he final answer is:?\s*\$?\\boxed\{", text)
    if start:
        boxed = boxed_content(text[start.start():])
        if boxed:
            return boxed
    found = re.findall(r"[Tt]he final answer is:?\s*([^\n.]+)", text)
    if found:
        answer = re.sub(r"^\$?\\boxed\{([^}]+)\}\$?$", r"\1", found[-1].strip()).replace("$", "").strip()
        if answer:
            return answer
    return NO_ANSWER


def boxed_content(text):
    """extract_boxed_content ACE: содержимое первого \\boxed{...} по балансу скобок; незакрытое — None."""
    m = re.search(r"\\boxed\{", text)
    if not m:
        return None
    end = matching(text, m.end() - 1, "{}")
    return None if end is None else text[m.end():end]


def dc_answer(text):
    """extract_answer DC (dynamic_cheatsheet/utils/extractor.py:12): после последнего <answer> до </answer>;
    иначе после последнего FINAL ANSWER (без двоеточия) — первый блок в ``` или ''' (какой встретится раньше);
    иначе NO_ANSWER."""
    text = text or ""
    if "<answer>" in text:
        return text.split("<answer>")[-1].strip().split("</answer>")[0].strip()
    if "FINAL ANSWER" not in text:
        return NO_ANSWER
    try:
        text = text.split("FINAL ANSWER")[-1].strip()
        if text[0] == ":":
            text = text[1:].strip()
        # разделитель блока: оба есть — тот, что раньше; один — он; ни одного — IndexError ниже, как у апстрима
        single, back = text.find("'''"), text.find("```")
        if min(single, back) != -1:
            text = text.split("'''" if single < back else "```")[1].strip()
        else:
            text = text.split("```" if single == -1 else "'''")[1].strip()
        if text.split("\n")[0].strip().lower() == "python":
            text = "\n".join(text.split("\n")[1:]).strip()
        return text
    except IndexError:
        return NO_ANSWER

# SCOPE (SCOPE/scope 4dc0da5): разбор ответов дословно, с откатами апстрима


def scope_json(text):
    """GuidelineSynthesizer._extract_json: весь текст, первый блок ```{...}```, первый {...} с update_text."""
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        pass
    blocks = re.findall(r'```(?:json)?\s*(\{.*?\})\s*```', text or "", re.DOTALL)
    data = first_json(blocks[:1])
    if data is not None:
        return data
    objects = re.findall(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', text or "", re.DOTALL)
    return first_json(objects, lambda data: "update_text" in data)


NO_IMPROVEMENT = ("", "no improvement needed", "none")     # кандидат без правила (synthesizer.py)


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
            if update.lower() in NO_IMPROVEMENT:
                return None
        return dict(update_text=update, rationale=data.get("rationale", ""),
                    confidence=data.get("confidence", "medium"))
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
    return first_json([text, text.replace("'", '"')])


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
        if c["scope"] == "strategic" and c["domain"] not in domains:
            c["domain"] = "general"
        c["confidence"] = float(c["confidence"])
        return c
    except (ValueError, TypeError, AttributeError, KeyError):
        return fallback


# общий разбор: свои промпты стенда со схемой ответа на проводе апстрима


def json_object(text):
    """Весь текст как JSON; иначе последний разобранный блок ```json; иначе последний разобранный объект {...}
    (рассуждающая модель упоминает JSON раньше итогового); иначе None."""
    if not text:
        return None
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass
    candidates = re.findall(r"```json\s*(.*?)\s*```", text, re.DOTALL) + braced(text)
    return first_json(reversed(candidates))


def structured(text, schema):
    """Ответ по pydantic-схеме из JSON в тексте (json_object); не разобралось или не та форма — None."""
    try:
        return schema.model_validate(json_object(text))
    except ValueError:
        return None


def gepa_fenced(text):
    """_has_fence_pair апстрима GEPA: в тексте две ограды ```."""
    return (text.find("```") + 3) < text.rfind("```")


def gepa_instruction(text):
    """ProposalAdapter.parse апстрима GEPA (strategies/instruction_proposal.py) по ответу без пробелов по краям:
    есть две ограды — текст между первой и последней без строки языка; нет — весь ответ без ограды в начале или в
    конце. None — ответ оборван (_is_known_truncated): начался с <think> и не закрыл его. Обрыв по длине (без двух
    оград) проверяет вызывающий: finish_reason у ответа, а не в тексте."""
    text = (text or "").strip()
    if not gepa_fenced(text) and text.lstrip().startswith("<think>") and text.count("<think>") > text.count("</think>"):
        return None
    if gepa_fenced(text):
        content = text[text.find("```") + 3:text.rfind("```")]
        match = re.match(r"^\S*\n", content)
        if match:
            content = content[match.end():]
        return content.strip()
    if text.startswith("```"):
        match = re.match(r"^```\S*\n?", text)
        if match:
            text = text[match.end():].strip()
    elif text.endswith("```"):
        text = text[:-3].strip()
    return text
