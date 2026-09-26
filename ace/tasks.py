"""Задачи: данные, инструкция решателю и проверка ответа. Проверки finer и formula — как в ACE, meb — как в DC
(сверка с эталонами: tests/bridge/test_bridge_tasks.py), dapo — как в TF-GRPO, hmmt — как в EvoLib, gpqa — наша.

dapo — DAPO-Math-17k в порядке апстрима TF-GRPO (scripts/data/process_training_free_GRPO_data.py: без дублей,
shuffle Random(42)), вопросы на английском с условием короче 160 символов: train — первые 40, val — следующие 10,
тест — ещё 40.
hmmt — бенчмарк EvoLib (eval_main.py _build_hmmt_task): MathArena/hmmt_feb_2025, hmmt_nov_2025, hmmt_feb_2026 подряд
(93 вопроса, в hmmt40 — первые 40), ответ — answer без пробелов по краям; только онлайн, без train и val.
symptom — бенчмарк MCE (env/symptom_diagnosis апстрима, данные gretelai/symptom_to_diagnosis) целиком, строки как у
апстрима: train 200, val 50, тест 212; выборки — первые SIZE / VAL_SIZE. Проверка — _normalize апстрима; решатель
среды апстрима (get_context и промпт диагноза) — у mce (solver/mce.py), общий решатель — ответ FINAL ANSWER.
aime — бенчмарк GEPA (gepa/examples/aime.py: init_dataset) целиком, строки как у апстрима: train и val — половины
AI-MO/aimo-validation-aime после shuffle Random(0) (по 45, с решением в additional_context), тест — MathArena/aime_2025
пять раз подряд (150); ответ — «### N», проверка — ContainsAnswerEvaluator апстрима (ответ входит в текст).
У общего решателя ответ — строка FINAL ANSWER в том же виде «### N»."""
import json
import re
from dataclasses import dataclass, field

from math_verify.metric import math_metric
from math_verify.parser import ExprExtractionConfig, LatexExtractionConfig

from . import config, matharena, prompts


@dataclass
class Task:
    """Задача: данные, системный промпт и инструкция решателю (prompts/task_<name>_system, _instr), проверка."""
    name: str
    system: str = field(init=False)
    instr: str = field(init=False)

    def __post_init__(self):
        self.system = prompts.text(f"task_{self.name}_system")
        self.instr = prompts.text(f"task_{self.name}_instr")

    def file(self, split="", size=None):
        """Файл данных: самая малая выборка с размером в имени не меньше size (formula_train40.jsonl), иначе
        бенчмарк целиком (symptom_train.jsonl); нет ни того ни другого — None. split: "" (тест) | "train" | "val";
        size по умолчанию из config."""
        size = size or default_size(split)
        name = f"{self.name}_{split}" if split else self.name
        sized = []              # (размер выборки, файл)
        for path in config.DATA.glob(f"{name}[0-9]*.jsonl"):
            suffix = path.stem[len(name):]
            if suffix.isdigit():
                sized.append((int(suffix), path))
        for n, path in sorted(sized):
            if n >= size:
                return path
        whole = config.DATA / f"{name}.jsonl"
        return whole if whole.exists() else None

    def load(self, split="", size=None, whole=False):
        """Первые size вопросов файла (whole — все); поля апстримов: input | context | question, target | answer.
        Нет файла или в нём меньше size вопросов — ошибка, а не молча меньше."""
        size = size or default_size(split)
        path = self.file(split, size)
        if path is None:
            raise FileNotFoundError(f"{self.name}: нет выборки {split or 'test'} на {size} вопросов в {config.DATA}")
        rows = [json.loads(line) for line in path.open() if line.strip()]
        items = []
        for r in rows:
            question = r.get("context") or r.get("input") or r["question"]
            item = {"question": question, "target": r.get("target", r.get("answer"))}
            if "additional_context" in r:       # GEPA: подсказка в обратную связь рефлексии (решение задачи)
                item["additional_context"] = r["additional_context"]
            items.append(item)
        if len(items) < size and not whole:
            raise ValueError(f"{self.name}: в {path.name} {len(items)} вопросов, а нужно {size}")
        return items if whole else items[:size]

    def check(self, answer, target):
        """Исключение проверки — неверно (как except у апстримов)."""
        try:
            return bool(CHECK[self.name](answer, target))
        except Exception:
            return False


def default_size(split):
    return config.VAL_SIZE if split == "val" else config.SIZE


def finer_counts(pred, tgt):
    """_finer_answer_is_correct апстрима ACE (eval/finance/data_processor.py:126) со счётом: (верных сущностей, всего).
    Ответ режется по запятой (и число с запятой тоже), лишнее отрезается, недостающее — пустые; пара сравнивается
    после eval, если он удался (у ответа снимается $), иначе строками."""
    got = [v.lower().strip() for v in pred.split(",")]
    want = [v.lower().strip() for v in tgt.split(",")]
    got = (got + [""] * len(want))[: len(want)]
    return sum(finer_same(p, g) for p, g in zip(got, want)), len(want)


def finer_ok(pred, tgt):
    count, total = finer_counts(pred, tgt)
    return count == total


def finer_same(p, g):
    try:
        g = arithmetic_eval(g)
        p = arithmetic_eval(p.replace(",", "").replace("$", ""))
    except Exception:
        pass
    return p == g


def formula_ok(pred, tgt):
    """_formula_answer_is_correct апстрима ACE (data_processor.py:154): без запятых числа сравниваются как float,
    иначе строки: `$15.00` против 15.0 неверно, нечисла — строкой."""
    pred, tgt = pred.replace(",", ""), tgt.replace(",", "")
    try:
        return float(pred) == float(tgt)
    except Exception:
        return pred == tgt


EVAL_CHARS = set("0123456789.+-*/() e_")
MEB_EPS = 1e-6


def arithmetic_eval(s):
    """eval апстримов (ACE finer, DC meb) только над арифметикой: цифры, точка, + - * / и скобки, без ** (9**9**9
    повесил бы процесс) и без имён; иначе ValueError, как неудавшийся eval апстрима."""
    if not set(s) <= EVAL_CHARS or "**" in s:
        raise ValueError(s)
    return eval(s, {"__builtins__": {}})


def meb_ok(pred, tgt):
    """eval_equation_balancer апстрима DC (dynamic_cheatsheet/utils/evaluation.py:151): левая часть ответа с теми же
    числами, что у эталона (операторы и пробелы не считаются), по значению равна правой части эталона.
    Знаки × ÷ апстрим не принимает."""
    out = pred.split("=")[0].strip()
    left, right = [part.strip() for part in tgt.split("=")[:2]]
    if numbers(out) != numbers(left):
        return False
    return abs(arithmetic_eval(out) - arithmetic_eval(right)) < MEB_EPS


def numbers(expression):
    """Числа выражения подряд: без + - * / и пробелов."""
    for sign in ("+", "-", "*", "/", " "):
        expression = expression.replace(sign, "")
    return expression.strip()


def dapo_ok(pred, tgt):
    """verify_func апстрима TF-GRPO (utu/practice/verify/math.py): эталон в \\boxed{}, math_verify по всему ответу,
    верно — награда 1.0."""
    verify = math_metric(gold_extraction_target=(LatexExtractionConfig(),),
                         pred_extraction_target=(ExprExtractionConfig(), LatexExtractionConfig()))
    score, _ = verify(["\\boxed{" + str(tgt) + "}"], [pred])
    return float(score) == 1.0


def hmmt_ok(pred, tgt):
    """eval_function HMMT апстрима EvoLib: extract_and_grade MathArena по тексту решения (ace/matharena)."""
    return matharena.grade(pred, tgt)


def symptom_ok(pred, tgt):
    """Проверка symptom_diagnosis апстрима MCE (symptom_diagnosis_environment.py: _normalize): нижний регистр,
    пробелы схлопнуты, без . ! ? в конце."""
    return symptom_normalize(pred) == symptom_normalize(tgt)


def symptom_normalize(text):
    return re.sub(r"\s+", " ", text.lower().strip()).rstrip(".!?")


def symptom_diagnosis(response):
    """_extract_diagnosis апстрима MCE: [DIAGNOSIS]...[/DIAGNOSIS], иначе «diagnosis:» / «conclusion:», иначе
    последняя строка."""
    match = re.search(r"\[DIAGNOSIS\](.*?)\[/DIAGNOSIS\]", response, re.IGNORECASE | re.DOTALL)
    if match:
        return match.group(1).strip()
    match = re.search(r"(?:diagnosis|conclusion)[:：]\s*([^\n]+)", response, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return response.strip().split("\n")[-1]


def aime_ok(pred, tgt):
    """ContainsAnswerEvaluator апстрима GEPA (adapters/default_adapter/default_adapter.py): эталон «### N» входит в
    ответ."""
    return tgt in pred


def gpqa_ok(pred, tgt):
    """Наша: буква варианта в начале ответа. Не eval_for_multiple_choice DC (тот принимает и текст варианта из
    вопроса): GPQA в стенде — наша задача, не из статей методов."""
    return pred.strip("()`*. ").upper()[:1] == tgt.strip("()").upper()[:1]


CHECK = {"finer": finer_ok, "formula": formula_ok, "meb": meb_ok, "gpqa": gpqa_ok, "dapo": dapo_ok, "hmmt": hmmt_ok,
         "symptom": symptom_ok, "aime": aime_ok}

TASKS = {name: Task(name) for name in CHECK}

# Метод × задача — единственное место, где метод узнаёт задачу по имени. На бенчмарке своего апстрима метод берёт
# его тексты, разбор входа и параметры (вариант); на остальных задачах — запасной вариант стенда "" (DEVIATIONS S2).
VARIANTS = {
    ("ace", "formula"): "formula",      # DataProcessor: вопрос между «Question: » и «. Answer:», приписка про число
    ("ace", "finer"): "instruction",    # DataProcessor: Instruction / Input
    ("dc", "meb"): "meb",               # вход с вступлением MathEquationBalancer
    ("tfgrpo", "dapo"): "math",         # math_agent.yaml и math_reasoning.yaml, в зачёт весь ответ (math_verify)
    ("evolib", "hmmt"): "math",         # HMMT_SOLVER_PROMPT, reasoning API, проверка по тексту решения
    ("mce", "symptom"): "symptom",      # интерфейс get_context, промпт диагноза, инструкция и поле symptoms
    ("gepa", "aime"): "aime",           # seed_prompt квикстарта, в зачёт весь ответ (ContainsAnswerEvaluator)
}


def variant(method, task):
    """Вариант метода на задаче (task — задача или её имя); "" — запасной вариант стенда."""
    return VARIANTS.get((method, getattr(task, "name", task)), "")


def accuracy(task, answers, targets):
    """Отчётная точность, как evaluate_accuracy апстрима ACE: у finer — доля верных сущностей по всем вопросам,
    у остальных — доля верных вопросов."""
    if task.name == "finer":
        counts = [finer_counts(a, t) for a, t in zip(answers, targets)]
        total = sum(n for _, n in counts)
        return sum(c for c, _ in counts) / total if total else 0.0
    return sum(task.check(a, t) for a, t in zip(answers, targets)) / len(answers) if answers else 0.0


def final_answer(text):
    """Строка после последнего 'FINAL ANSWER:', иначе последняя строка."""
    if "FINAL ANSWER:" in text:
        tail = text.rsplit("FINAL ANSWER:", 1)[-1]
    else:
        tail = text.strip().rsplit("\n", 1)[-1]
    return tail.strip().split("\n")[0].strip("`*. ")

