"""Сериализации: всё, что из данных стенда сшивается в текст для модели. Формулировки — шаблоны в ace/prompts/
(строки стенда — stand.j2, строки апстримов — <метод>_strings.j2), здесь только сборка: строки записей и раскладки
памяти, файловые инструменты, сообщение решателю, траектория, вердикт, поля промптов SCOPE, TF-GRPO, MCE, хуков,
вывод песочницы. Каждую сериализацию, взятую у апстрима, сверяют с ним по этому модулю."""
import json
import re

from pydantic_ai.messages import TextPart, ToolCallPart, ToolReturnPart

from . import prompts
from .tasks import variant

STAND = prompts.macros("stand")
SCOPE = prompts.macros("scope_strings")
TFGRPO = prompts.macros("tfgrpo_strings")
MCE = prompts.macros("mce_strings")
DC = prompts.macros("dc_strings")

EMPTY = STAND.empty()

# строка записи


def plain(r):
    return r.text


def dashed(r):
    return f"- {r.text}"


def numbered(r):
    return f"[{r.id}] {r.text}"


def counted(r):
    """Пункт ACE: «[id] helpful=N harmful=M :: текст» (формат playbook апстрима)."""
    return f"[{r.id}] helpful={r.helpful} harmful={r.harmful} :: {r.text}"


def prefixed(prefix):
    def line(r):
        return prefix + r.text
    return line


def lines(records, line=numbered, sep="\n"):
    return sep.join(line(r) for r in records)


def bullets(texts):
    """Тексты строками «- текст»."""
    return "\n".join(f"- {t}" for t in texts)

# раскладки памяти


def pairs(records, scored, note=""):
    """Пары (вопрос, решение) в оформлении DC. scored (retrieval): пояснение note, у каждой пары близость, самая
    похожая последней; иначе (полная история) по порядку."""
    text = DC.pairs_start() + "\n\n"
    if not scored:
        for i, r in enumerate(records):
            text += DC.pair(n=i + 1, question=r.question, solution=r.text)
        return text + DC.pairs_end()
    text += note + "\n\n"
    for i, r in enumerate(records[::-1]):
        text += DC.scored_pair(n=i + 1, similarity=r.score, question=r.question, solution=r.text)
    return text.strip() + "\n\n" + DC.pairs_end()

# файловые инструменты (fs.py)


def listing(base, folders, files):
    """Содержимое папки base: подпапки со слешем, затем файлы (имя, краткая строка); пустая — EMPTY."""
    rows = [f"{base}/{name}/" for name in folders] + [f"{base}/{name}  {head}" for name, head in files]
    return "\n".join(rows) or EMPTY


def mounts(modes):
    """Точки монтирования с режимом: «context/  (rw)»; modes — пары (имя, режим)."""
    return "\n".join(f"{name}/  ({mode})" for name, mode in modes)


def numbered_lines(rows, start):
    """Строки файла с номерами «N: текст» от start."""
    return "\n".join(f"{i}: {row}" for i, row in enumerate(rows, start))

# решатель и его траектория


def user_message(instr, question, note=""):
    """Инструкция задачи, вопрос и заметка рефлектора (раунды ACE)."""
    return prompts.text("user_message", instr=instr, question=question, note=note)


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
    if isinstance(content, str):
        return STAND.tool_error(message=content)
    return STAND.tool_error(message="; ".join(e["msg"] for e in content))


def verdict(ok, target=""):
    if ok is None:
        return STAND.unknown()
    if ok:
        return STAND.correct()
    if target:
        return STAND.wrong_answer(target=target)
    return STAND.wrong()


def python_output(stdout, stderr):
    return f"[stdout]\n{stdout}\n[stderr]\n{stderr}".strip()

# TF-GRPO: ответ инструмента execute_python_code, когда ядро не ответило — str(dict) как у python_executor апстрима


def kernel_failed(error):
    return str({"success": False, "stdout": "", "stderr": "", "status": False, "output": "", "files": [], "error": error})


def kernel_timeout(seconds):
    """timed_out ядра (tfgrpo_kernel.py): тот же текст, что при пределе внутри ядра."""
    return kernel_failed(TFGRPO.timed_out(seconds=seconds))


def kernel_died():
    return kernel_failed(STAND.kernel_died())

# рефлексия стенда и хуки


ERROR_TAIL = 500        # хвост ошибки инструмента: traceback важен в конце
ARGS_HEAD = 300         # начало аргументов вызова


def failed_steps(steps):
    """Шаги с ошибкой, по номерам: вызов и хвост ошибки."""
    blocks = []
    for i, (name, args, result) in enumerate(steps, 1):
        blocks.append(f"{i}. {name} {args[:ARGS_HEAD]}\n{result[-ERROR_TAIL:]}")
    return "\n\n".join(blocks)


def hooks(records):
    return "\n".join(STAND.hook(trigger=r.trigger, lesson=r.text) for r in records) or STAND.nothing()


def raw_hook(name, args):
    return prompts.text("hook_raw", name=name, args=args[:ERROR_TAIL])

# ACE


def pretty_json(values):
    """JSON с отступом 2, как json.dumps(..., indent=2) апстримов: статистика playbook ACE, evaluations.json MCE."""
    return json.dumps(values, indent=2)


def ace_playbook(sections):
    """Playbook ACE текстом, как его ведёт апстрим: пустой — заголовки через пустую строку
    (_initialize_empty_playbook), новый пункт — в конец раздела, после этой пустой строки и перед следующим
    заголовком (apply_curator_operations); у последнего раздела пустой строки нет. sections — пары (заголовок,
    записи)."""
    rows = []
    for i, (title, records) in enumerate(sections):
        rows.append(f"## {title}")
        if i < len(sections) - 1:
            rows.append("")
        rows += [counted(r) for r in records]
    return "\n".join(rows)


def bullets_used(records):
    """Пункты, которые назвал решатель, для рефлектора (extract_playbook_bullets): строка пункта с первой строкой
    текста — апстрим разбирает playbook построчно."""
    rows = []
    for r in records:
        first = r.text.split("\n")[0].strip()
        rows.append(f"[{r.id}] helpful={r.helpful} harmful={r.harmful} :: {first}")
    return "\n".join(rows)


def merge_group(records):
    """Группа похожих пунктов для слияния (BulletpointAnalyzer)."""
    return "\n".join(f"{k + 1}. {counted(r)}" for k, r in enumerate(records))

# SCOPE; обрезки как в апстриме по умолчанию (truncate_context=True)


OUTPUT_CUT = 200            # _build_step_summary: model_output[:200]
TOOLS_CUT = 150             # tool_calls[:150]
OBSERVATIONS_CUT = 150      # observations[:150]


def cut(s, n):
    return s[:n] + "..." if len(s) > n else s


def step_summary(output="", tools="", observations=""):
    parts = []
    if output:
        parts.append(SCOPE.model_output(text=cut(output, OUTPUT_CUT)))
    if tools:
        parts.append(SCOPE.tool_calls(text=cut(tools, TOOLS_CUT)))
    if observations:
        parts.append(SCOPE.observations(text=cut(observations, OBSERVATIONS_CUT)))
    return "\n".join(parts) or SCOPE.no_details()


def tool_call(name, args):
    return f"{name} {args}"


def tool_error(result):
    """Ошибка шага с инструментом: (тип, хвост ошибки)."""
    return STAND.tool_error_type(), result[-ERROR_TAIL:]


def incorrect_answer(answer, target):
    return STAND.incorrect_answer_type(), STAND.incorrect_answer(answer=answer, target=target)


def truncated_answer():
    return STAND.truncated_type(), STAND.truncated()


def answer_seen(ok):
    return "" if ok is None else STAND.answer_seen(ok=ok)


def rules(texts):
    return bullets(texts) or SCOPE.no_rules()


def candidates(items):
    out = ""
    for i, c in enumerate(items):
        out += SCOPE.candidate(i=i, update=c.update_text, rationale=c.rationale, confidence=c.confidence)
    return out


def issue(step, error):
    if not error:
        return SCOPE.step_details(step=step)
    kind, message = error
    return SCOPE.issue(step=step, type=kind, message=message)


def strategic(intro, text):
    """Strategic правила для классификатора (get_strategic_rules_text); пусто без правил."""
    return "\n" + intro + text if text else ""


def domains(groups):
    """Strategic правила по доменам (get_strategic_rules_text): groups — пары (домен, правила), пустые
    домены пропускаются; tool_usage -> Tool Usage."""
    blocks = []
    for domain, rules in groups:
        if rules:
            title = domain.replace("_", " ").title()
            blocks.append("\n".join([SCOPE.domain(title=title)] + [dashed(r) for r in rules]))
    return "\n\n".join(blocks)


def allowed_domains(names):
    return ", ".join(names)


def rule_list(rules):
    """Правила для анализа оптимизатором."""
    return "".join(SCOPE.rule(id=x["id"], text=x["rule"]) for x in rules)


def rule_group(rules):
    """Правила для слияния оптимизатором."""
    return "".join(SCOPE.rule_block(id=x["id"], text=x["rule"], rationale=x["rationale"]) for x in rules)

# TF-GRPO


def attempts(pairs, labeled):
    """Сводки попыток группы с наградой 0/1; без метки награда скрыта."""
    blocks = []
    for i, (episode, summary) in enumerate(pairs):
        reward = float(bool(episode.ok)) if labeled else TFGRPO.redacted()
        blocks.append(TFGRPO.attempt(n=i + 1, reward=reward, summary=summary))
    return "\n\n".join(blocks)


def label(i):
    """Опыт по месту в библиотеке: G0, G1, ... — ключи апстрима, которые он заново раздаёт после каждого батча."""
    return f"G{i}"


def experiences(records):
    rows = [TFGRPO.experience(label=label(i), text=r.text) for i, r in enumerate(records)]
    return "\n".join(rows) or TFGRPO.no_experiences()


def batch_table(records, ops):
    """Опыты с относящимися к ним операциями, затем операции без id."""
    def dump(op):
        return json.dumps(op, ensure_ascii=False, indent=2)
    table = []
    for i, r in enumerate(records):
        related = [dump(op) for op in ops if op.get("id") == label(i)]
        table.append(dict(id=label(i), text=r.text, related=related))
    loose = [dump(op) for op in ops if not op.get("id")]
    return prompts.text("tfgrpo_batch_table", ops=bool(ops), experiences=table, loose=loose)

# MCE (mce/prompts/meta_agent.py, utils.py, main.py): строки и json — как у апстрима

OVERVIEW = re.compile(r"^##\s*Skill\s+Overview\s*$", re.MULTILINE | re.IGNORECASE)
NEXT_SECTION = re.compile(r"\n##\s+[^#]")


def overview(skill):
    """_extract_skill_overview: раздел «## Skill Overview» навыка с отступом; None — SKILL.md нет."""
    if skill is None:
        return MCE.no_skill_file()
    match = OVERVIEW.search(skill)
    if not match:
        return MCE.no_overview()
    rest = skill[match.end():]
    end = NEXT_SECTION.search(rest)
    text = (rest[:end.start()] if end else rest).strip()
    if not text:
        return MCE.empty_overview()
    return "\n".join(f"  {line}" if line.strip() else "" for line in text.split("\n"))


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
        entries.append(MCE.iteration(i=i, train=f"{data[f'train_{metric}']:.2%}", val=f"{data[f'val_{metric}']:.2%}",
                                     rollouts=data.get("total_rollouts", 0), subs=data.get("num_sub_iters", 1),
                                     overview=overview(skills.get(f"iter{i}")),
                                     folder=data.get("last_sub_folder", f"iter{i}")))
    return "\n\n".join(entries) or prompts.text("mce_only_baseline")


def signature_args(inputs):
    """Параметры интерфейса для промптов: «symptoms: str» через запятую; inputs — (имя, тип, описание)."""
    return ", ".join(f"{name}: {typ}" for name, typ, _ in inputs)


def train_json(summary, results):
    """data/train.json под-итерации: сводка батча и итоги его вопросов."""
    return json.dumps(dict(summary=summary, detailed_results=results), indent=2, ensure_ascii=False)


def jsonl(rows):
    """meta_agent/train.jsonl."""
    return "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)


def skilled(system, ex):
    """Системный промпт обучения с навыком от мета-уровня (ex.skill, MCE); без навыка — как был."""
    skill = getattr(ex, "skill", "")
    if not skill:
        return system
    return system + "\n\n" + prompts.text("meta_skill", skill=skill)


def task_instruction(task):
    """Инструкция задачи агентам MCE: у бенчмарка апстрима — его get_task_instruction (mce_task_<задача>), у
    задач стенда — системный промпт и инструкция решателю (S2)."""
    if variant("mce", task) == "symptom":
        return prompts.text("mce_task_symptom")
    return f"{task.system} {task.instr}"
