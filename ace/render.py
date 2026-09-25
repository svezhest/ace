"""Сериализации: всё, что из данных стенда сшивается в текст для модели. Формулировки — шаблоны в
ace/prompts/, здесь только сборка: строки записей и раскладки памяти, сообщения решателю, траектория,
вердикт, поля промптов SCOPE, TF-GRPO, EvoLib, MCE, хуков, вывод песочницы.
Каждую сериализацию, взятую у апстрима, сверяют с ним по этому модулю."""
import json
import re

from pydantic_ai.messages import TextPart, ToolCallPart, ToolReturnPart

from . import prompts
from .tasks import variant

NONE, EMPTY = "(none)", "(empty)"

# строка записи


def plain(r):
    return r.text


def dashed(r):
    return f"- {r.text}"


def numbered(r):
    return f"[{r.id}] {r.text}"


def counted(r):
    return f"[{r.id}] helpful={r.helpful} harmful={r.harmful} :: {r.text}"


def prefixed(prefix):
    return lambda r: prefix + r.text


def lines(records, line=numbered, sep="\n"):
    return sep.join(line(r) for r in records)

# раскладки памяти


def titled(groups, line, header="## {}", sep="\n\n"):
    """Группы записей под заголовками: groups — пары (заголовок, записи); пустые группы тоже показываются."""
    return sep.join("\n".join([header.format(t)] + [line(r) for r in records]) for t, records in groups)


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
    """Отбивка инструмента: строка ModelRetry или список ошибок валидации pydantic (все, через «; »)."""
    return f"Error: {content if isinstance(content, str) else '; '.join(e['msg'] for e in content)}"


def verdict(ok, target=""):
    if ok is None:
        return "unknown"
    if ok:
        return "correct"
    return f"wrong, correct answer: {target}" if target else "wrong"


def python_output(stdout, stderr):
    return f"[stdout]\n{stdout}\n[stderr]\n{stderr}".strip()


NO_RESPONSE = "sandbox: the container did not respond"


def omitted(n):
    """Строка на месте вырезанной середины длинного вывода."""
    return f"... {n} lines omitted ..."


def more_lines(left, offset):
    """Хвост постраничного read: сколько строк осталось и откуда читать дальше."""
    return f"... {left} more lines; read with offset={offset}"


def time_limit(seconds):
    return f"sandbox: time limit of {seconds} s exceeded"

# TF-GRPO: ответ инструмента execute_python_code, когда ядро не ответило — str(dict) как у python_executor апстрима


def kernel_failed(error):
    return str({"success": False, "stdout": "", "stderr": "", "status": False, "output": "", "files": [], "error": error})


def kernel_timeout(seconds):
    """timed_out ядра (tfgrpo_kernel.py): тот же текст, что при пределе внутри ядра."""
    return kernel_failed(f"Code execution timed out ({seconds} seconds)")


KERNEL_DIED = kernel_failed("Kernel died (out of memory or crashed); variables are lost")

# DC: исполнение кода генератора (utils/execute_code.py, language_model.py апстрима)

DC_NO_RESPONSE = "(No response generated)"
DC_NO_BLOCK = "(No code block found to execute)"
DC_NO_OUTPUT = ("(No output was generated. It is possible that you did not include a print statement in your code. "
                "If you want to see the output, please include a print statement.)")
DC_TIMEOUT = "Execution took too long, aborting..."


def dc_code_output(output):
    return f"Output of the Python code above:\n```\n{output}\n```"


def dc_code_error(error):
    return f"PYTHON CODE OUTPUT:\n```\nError: {error}\n```"


def dc_execution_error(stderr):
    return f"Error in execution: {stderr}"

# рефлексия стенда и хуки


ERROR_TAIL = 500        # хвост ошибки инструмента: traceback важен в конце
ARGS_HEAD = 300         # начало аргументов вызова


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


def ace_playbook(sections):
    """Playbook ACE текстом, как его ведёт апстрим: пустой — заголовки через пустую строку
    (_initialize_empty_playbook), новый пункт — в конец раздела, после этой пустой строки и перед следующим
    заголовком (apply_curator_operations); у последнего раздела пустой строки нет. sections — пары (заголовок,
    записи)."""
    lines = []
    for i, (title, records) in enumerate(sections):
        lines += [f"## {title}"] + ([""] if i < len(sections) - 1 else []) + [counted(r) for r in records]
    return "\n".join(lines)


def bullets_used(records):
    """Пункты, которые назвал решатель, для рефлектора (extract_playbook_bullets): строка пункта с первой строкой
    текста — апстрим разбирает playbook построчно."""
    first = lambda text: text.split("\n")[0].strip()
    return "\n".join(f"[{r.id}] helpful={r.helpful} harmful={r.harmful} :: {first(r.text)}" for r in records)


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


def domains(groups):
    """Strategic правила по доменам (get_strategic_rules_text): groups — пары (домен, правила), пустые
    домены пропускаются; tool_usage -> Tool Usage."""
    return titled([(d.replace("_", " ").title(), rules) for d, rules in groups if rules], dashed, header="### {}:")


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


def label(i, r):
    """Опыт по месту в библиотеке: G0, G1, ... — ключи апстрима, которые он заново раздаёт после каждого батча."""
    return f"G{i}"


def experiences(records):
    return "\n".join(f"[{label(i, r)}]. {r.text}" for i, r in enumerate(records)) or "None"


def batch_table(records, ops):
    """Опыты с относящимися к ним операциями, затем операции без id."""
    dump = lambda op: json.dumps(op, ensure_ascii=False, indent=2)
    table = [dict(id=label(i, r), text=r.text, related=[dump(op) for op in ops if op.get("id") == label(i, r)])
             for i, r in enumerate(records)]
    return prompts.text("tfgrpo_batch_table", ops=bool(ops), experiences=table, loose=[dump(op) for op in ops if not op.get("id")])

# EvoLib


def evaluation(verdict):
    return f"\nEvaluation: {verdict}\n"

# MCE (mce/prompts/meta_agent.py, utils.py, main.py): строки и json — как у апстрима

OVERVIEW = re.compile(r"^##\s*Skill\s+Overview\s*$", re.MULTILINE | re.IGNORECASE)
NEXT_SECTION = re.compile(r"\n##\s+[^#]")


def overview(skill):
    """_extract_skill_overview: раздел «## Skill Overview» навыка с отступом; None — SKILL.md нет."""
    if skill is None:
        return "  (SKILL.md not found)"
    match = OVERVIEW.search(skill)
    if not match:
        return "  (no '## Skill Overview' section found)"
    rest = skill[match.end():]
    end = NEXT_SECTION.search(rest)
    text = (rest[:end.start()] if end else rest).strip()
    if not text:
        return "  (Skill Overview section is empty)"
    return "\n".join(f"  {l}" if l.strip() else "" for l in text.split("\n"))


def skill_database(evaluations, skills, current):
    """_build_skill_database: прошлые итерации из evaluations.json (без записи — пропуск), метрика — первый ключ
    val_metrics; skills — iter{i} -> текст SKILL.md; current — номер текущей итерации."""
    if current == 0:
        return prompts.text("mce_no_iterations_iter0")
    if current == 1:
        return prompts.text("mce_no_iterations")
    entries = []
    for i in range(1, current):
        data = evaluations.get(f"iter{i}")
        if data is None:
            continue
        metric = next(iter(data.get("val_metrics") or {}), "accuracy")
        subs = data.get("num_sub_iters", 1)
        entries.append(f"### Iteration {i}\n- **Train**: {data[f'train_{metric}']:.2%} | **Val**: {data[f'val_{metric}']:.2%}\n"
                       f"- **Rollouts**: {data.get('total_rollouts', 0)} ({subs} sub-iteration{'s' if subs > 1 else ''})\n"
                       f"- **Skill Overview**:\n{overview(skills.get(f'iter{i}'))}\n"
                       f"- **Files**: `meta_agent/skills/iter{i}/SKILL.md`, `{data.get('last_sub_folder', f'iter{i}')}/`")
    return "\n\n".join(entries) or prompts.text("mce_only_baseline")


def evaluations(values):
    """meta_agent/evaluations.json."""
    return json.dumps(values, indent=2)


def train_json(summary, results):
    """data/train.json под-итерации: сводка батча и итоги его задач."""
    return json.dumps(dict(summary=summary, detailed_results=results), indent=2, ensure_ascii=False)


def jsonl(rows):
    """meta_agent/train.jsonl."""
    return "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)


def skilled(system, ex):
    """Системный промпт обучения с навыком от мета-уровня (ex.skill, MCE); без навыка — как был."""
    skill = getattr(ex, "skill", "")
    return system + "\n\n" + prompts.text("meta_skill", skill=skill) if skill else system


def task_instruction(task):
    """Инструкция задачи агентам MCE: у бенчмарка апстрима — его get_task_instruction (mce_task_<задача>), у
    задач стенда — системный промпт и инструкция решателю (S2)."""
    if variant("mce", task) == "symptom":
        return prompts.text("mce_task_symptom")
    return f"{task.system} {task.instr}"
