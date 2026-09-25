"""Сериализации: всё, что из данных стенда сшивается в текст для модели. Формулировки — шаблоны в
ace/prompts/, здесь только сборка: строки записей и раскладки памяти, сообщения решателю, траектория,
вердикт, поля промптов SCOPE, TF-GRPO, EvoLib, MCE, хуков, вывод песочницы.
Каждую сериализацию, взятую у апстрима, сверяют с ним по этому модулю."""
import json

from pydantic_ai.messages import TextPart, ToolCallPart, ToolReturnPart

from . import prompts

NONE, EMPTY = "(none)", "(empty)"

# строка записи


def plain(r):
    return r.text


def dashed(r):
    return f"- {r.text}"


def numbered(r):
    return f"[{r.id}] {r.text}"


def dotted(r):
    return f"[{r.id}]. {r.text}"


def counted(r):
    return f"[{r.id}] helpful={r.helpful} harmful={r.harmful} :: {r.text}"


def prefixed(prefix):
    return lambda r: prefix + r.text


def lines(records, line=numbered, sep="\n"):
    return sep.join(line(r) for r in records)

# раскладки памяти


def grouped(records, line, group, groups, header, sep):
    """Записи под заголовками: groups — пары (группа, заголовок), group(r) — группа записи."""
    return sep.join("\n".join([header.format(t)] + [line(r) for r in records if group(r) == g]) for g, t in groups)


def pairs(records, scored, note=""):
    """Пары (вопрос, решение) в оформлении DC. scored (retrieval): с пояснением note и близостью,
    самая похожая последней; иначе (полная история) по порядку. Двойной пробел в «Input  #» — как в апстриме."""
    text = "### PREVIOUS SOLUTIONS (START)\n\n" + (f"{note}\n\n" if scored else "")
    for i, r in enumerate(records[::-1] if scored else records):
        if scored:
            text += (f"#### Previous Input #{i + 1} (Similarity: {r.score:.2f}):\n\n{r.question}\n\n"
                     f"#### Model Solution to Previous Input  #{i + 1}:\n\n{r.text}\n---\n---\n\n")
        else:
            text += (f"#### Previous Input #{i + 1}:\n\n{r.question}\n\n"
                     f"#### Model Solution to Previous Input #{i + 1}:\n\n{r.text}\n---\n---\n\n")
    return (text.strip() + "\n\n" if scored else text) + "#### PREVIOUS SOLUTIONS (END)"


def files(records):
    """Память как файлы для куратора ACE стенда."""
    return "\n".join(f"memory/{r.id}: {r.text}" for r in records) or EMPTY


def entries(records):
    """Типизированные записи прототипа для куратора."""
    return "\n".join(f"[{r.id}] ({r.kind}; when: {r.when}) {r.text}" for r in records) or EMPTY


def typed_lesson(kind, when, text):
    return f"{kind}, when {when}: {text}"


def lessons(items):
    """Уроки дельты для куратора."""
    return "\n".join(f"- {l}" for l in items)

# решатель и его траектория


def user_message(instr, context, note=""):
    """Инструкция задачи, вопрос и заметка рефлектора (раунды ACE)."""
    return f"{instr}\n\n{context}" + (f"\n\nReflection:\n{note}" if note else "")


def transcript(messages):
    """Вся траектория текстом: ответы модели, вызовы инструментов и их результаты."""
    out = []
    for m in messages:
        for p in m.parts:
            if isinstance(p, TextPart) and p.content:
                out.append(p.content)
            elif isinstance(p, ToolCallPart):
                out.append(f"[call {p.tool_name}] {p.args_as_json_str()}")
            elif isinstance(p, ToolReturnPart):
                out.append(f"[{p.tool_name}] {p.content}")
    return "\n\n".join(out)


def retry_error(content):
    """Отбивка инструмента: строка ModelRetry или список ошибок валидации pydantic (первая)."""
    return f"Error: {content if isinstance(content, str) else content[0]['msg']}"


def verdict(ok, target=""):
    if ok is None:
        return "unknown"
    if ok:
        return "correct"
    return f"wrong, correct answer: {target}" if target else "wrong"


def python_output(stdout, stderr):
    return f"[stdout]\n{stdout}\n[stderr]\n{stderr}".strip()

# рефлексия стенда и хуки


ERROR_TAIL = 500        # хвост ошибки инструмента: traceback важен в конце
ARGS_HEAD = 300         # начало аргументов вызова


def used(records):
    """Записи, прочитанные решателем (рефлексия прототипа)."""
    return "\n".join(f"[{r.id}] {r.text}" for r in records) or NONE


def failures(steps):
    """Шаги с ошибкой, по номерам: вызов и хвост ошибки."""
    return "\n\n".join(f"{i}. {name} {args[:ARGS_HEAD]}\n{result[-ERROR_TAIL:]}" for i, (name, args, result) in enumerate(steps, 1))


def hooks(records):
    return "\n".join(f"- trigger: {r.trigger}\n  lesson: {r.text}" for r in records) or NONE


def raw_hook(name, args):
    return prompts.text("hook_raw", name=name, args=args[:ERROR_TAIL])

# ACE


def stats(values):
    """Статистика плейбука для куратора."""
    return json.dumps(values, indent=2)


def merge_group(records):
    """Группа похожих пунктов для слияния (BulletpointAnalyzer)."""
    return "\n".join(f"{k + 1}. {counted(r)}" for k, r in enumerate(records))

# SCOPE; обрезки как в апстриме по умолчанию (truncate_context=True)


OUTPUT_CUT, TOOLS_CUT, OBSERVATIONS_CUT = 200, 150, 150


def cut(s, n):
    return s[:n] + "..." if len(s) > n else s


def step_summary(output="", tools="", observations=""):
    parts = [f"Model output: {cut(output, OUTPUT_CUT)}" if output else "", f"Tool calls: {cut(tools, TOOLS_CUT)}" if tools else "",
             f"Observations: {cut(observations, OBSERVATIONS_CUT)}" if observations else ""]
    return "\n".join(p for p in parts if p) or "(no step details)"


def tool_call(name, args):
    return f"{name} {args}"


def tool_error(result):
    return "ToolError", result[-ERROR_TAIL:]


def incorrect_answer(answer, target):
    return "IncorrectAnswer", f"Incorrect answer. Model answered '{answer}'" + (f", expected '{target}'." if target else ".")


def truncated_answer():
    return "Truncated", "The output was cut at the token limit before the final answer."


def answer_seen(ok):
    return "" if ok is None else f"Answer {'correct' if ok else 'incorrect'}"


def system_prompt(system, context):
    """Системный промпт агента, как его видит SCOPE: роль и показанная память."""
    return f"{system}\n\n{context}".strip()


def rules(texts):
    return "\n".join(f"- {r}" for r in texts) or NONE


def candidates(items):
    return "".join(f"\n[Candidate {i}]\nUpdate: {c.update_text}\nRationale: {c.rationale}\nConfidence: {c.confidence}\n"
                   for i, c in enumerate(items))


def issue(step, error):
    return f"Error Type: {error[0]}\nError Message: {error[1]}\n\nLast Step:\n{step}" if error else f"Step Details:\n{step}"


def strategic(intro, text):
    """Strategic правила для классификатора (get_strategic_rules_text); пусто без правил."""
    return "\n" + intro + text if text else ""


def rule_list(rules):
    """Правила для анализа оптимизатором."""
    return "".join(f"Rule {x['id']}: {x['rule']}\n" for x in rules)


def rule_group(rules):
    """Правила для слияния оптимизатором."""
    return "".join(f"\nRule {x['id']}:\n  Text: {x['rule']}\n  Rationale: {x['rationale']}\n" for x in rules)

# TF-GRPO


REDACTED = "[REDACTED]"
NO_CRITIQUE = "[No critique provided]"


def attempts(pairs, labeled):
    """Сводки попыток группы с наградой 0/1; без метки награда скрыта."""
    return "\n\n".join(f"Attempt {i + 1} (Reward {float(bool(g.ok)) if labeled else REDACTED}):\n{s}" for i, (g, s) in enumerate(pairs))


def experiences(records):
    return "\n".join(f"[{r.id}]. {r.text}" for r in records) or "None"


def batch_table(records, ops):
    """Опыты с относящимися к ним операциями, затем операции без id."""
    dump = lambda op: json.dumps(op, ensure_ascii=False, indent=2)
    table = [dict(id=r.id, text=r.text, related=[dump(op) for op in ops if op.get("id") == r.id]) for r in records]
    return prompts.text("tfgrpo_batch_table", ops=bool(ops), experiences=table, loose=[dump(op) for op in ops if not op.get("id")])

# EvoLib


def evaluation(verdict):
    return f"\nEvaluation: {verdict}\n"

# MCE


def overview(skill):
    """Раздел «## Skill Overview» навыка с отступом."""
    out, inside = [], False
    for l in skill.splitlines():
        if l.strip().lower().replace(" ", "") == "##skilloverview":
            inside = True
            continue
        if inside and l.startswith("## "):
            break
        if inside:
            out.append(l)
    text = "\n".join(out).strip()
    return "\n".join(f"  {l}" if l.strip() else "" for l in text.splitlines()) if text else "  (no '## Skill Overview' section found)"


def skill_database(done):
    """Прошлые итерации (без нулевой): точность и обзор навыка."""
    if not done:
        return prompts.text("mce_no_iterations")
    return "\n\n".join(f"### Iteration {i}\n- **Train**: {h.train:.2%} | **Val**: {h.val:.2%}\n"
                       f"- **Skill Overview**:\n{overview(h.text)}" for i, h in enumerate(done, 1))


def evaluations(history):
    return json.dumps({f"iter{i}": dict(val_accuracy=h.val, train_accuracy=h.train) for i, h in enumerate(history)}, indent=2)


def skills(done):
    return "\n\n".join(f"### iter{i}/SKILL.md\n{h.text}" for i, h in enumerate(done, 1)) or NONE


def task_instruction(task):
    return f"{task.system} {task.instr}"


def train_summary(correct, total):
    return f"train_accuracy {correct}/{total}"


def result(ok, answer, target, question):
    """Итог задачи батча для базового агента (data/)."""
    return f"is_correct: {bool(ok)}\nllm_answer: {answer}\ntarget: {target}\nquestion:\n{question}"
