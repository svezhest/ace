"""Задачи: данные, инструкция решателю и проверка ответа. Проверки finer и formula — как в ACE, meb — как в DC
(сверка с эталонами: tests/bridge/test_bridge_tasks.py), gpqa — наша."""
import json
from dataclasses import dataclass, field

from . import config, prompts


@dataclass
class Task:
    """Задача: данные, системный промпт и инструкция решателю (prompts/task_<name>_system, _instr), проверка."""
    name: str
    system: str = field(init=False)
    instr: str = field(init=False)

    def __post_init__(self):
        self.system = prompts.text(f"task_{self.name}_system")
        self.instr = prompts.text(f"task_{self.name}_instr")

    def load(self, split="", size=None):
        """split: "" | "train" | "val"; size — размер выборки в имени файла (по умолчанию из config)."""
        size = size or (config.VAL_SIZE if split == "val" else config.SIZE)
        file = config.DATA / f"{self.name}{'_' + split if split else ''}{size}.jsonl"
        rows = [json.loads(l) for l in file.open() if l.strip()]
        return [{"context": r.get("context") or r["input"], "target": r["target"]} for r in rows]

    def accuracy(self, answers, targets):
        """Отчётная точность, как evaluate_accuracy апстрима ACE: у finer — доля верных сущностей по всем вопросам,
        у остальных — доля верных вопросов."""
        if self.name == "finer":
            counts = [finer_counts(a, t) for a, t in zip(answers, targets)]
            total = sum(n for _, n in counts)
            return sum(c for c, _ in counts) / total if total else 0.0
        return sum(self.check(a, t) for a, t in zip(answers, targets)) / len(answers) if answers else 0.0

    def check(self, answer, target):
        """Исключение проверки — неверно (как except у апстримов)."""
        try:
            return bool(CHECK[self.name](answer, target))
        except Exception:
            return False


def finer_counts(pred, tgt):
    """_finer_answer_is_correct апстрима ACE (eval/finance/data_processor.py:126) со счётом: (верных сущностей, всего).
    Ответ режется по запятой (и число с запятой тоже), лишнее отрезается, недостающее — пустые; пара сравнивается
    после eval, если он удался (у ответа снимается $), иначе строками."""
    got, want = [v.lower().strip() for v in pred.split(",")], [v.lower().strip() for v in tgt.split(",")]
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
    out, want, ref = pred.split("=")[0].strip(), tgt.split("=")[1].strip(), tgt.split("=")[0].strip()
    nums = lambda s: s.replace("+", "").replace("-", "").replace("*", "").replace("/", "").replace(" ", "").strip()
    if nums(out) != nums(ref):
        return False
    return abs(arithmetic_eval(out) - arithmetic_eval(want)) < MEB_EPS


def gpqa_ok(pred, tgt):
    """Наша: буква варианта в начале ответа. Не eval_for_multiple_choice DC (тот принимает и текст варианта из
    вопроса): GPQA в стенде — наша задача, не из статей методов."""
    return pred.strip("()`*. ").upper()[:1] == tgt.strip("()").upper()[:1]


CHECK = {"finer": finer_ok, "formula": formula_ok, "meb": meb_ok, "gpqa": gpqa_ok}

TASKS = {name: Task(name) for name in ("finer", "formula", "meb", "gpqa")}


def final_answer(text):
    """Строка после последнего 'FINAL ANSWER:', иначе последняя строка."""
    tail = text.rsplit("FINAL ANSWER:", 1)[-1] if "FINAL ANSWER:" in text else text.strip().rsplit("\n", 1)[-1]
    return tail.strip().split("\n")[0].strip("`*. ")


def replay(task, log):
    """Номера записей старого log.json, где проверка сейчас судит иначе, чем при прогоне."""
    return [r["i"] for r in log if task.check(r["answer"], r["target"]) != r["correct"]]
