"""Задачи: данные, инструкция решателю и проверка ответа. Чекеры повторяют ACE, чтобы числа были сравнимы."""
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

    def check(self, answer, target):
        try:
            return bool(answer.strip()) and bool(CHECK[self.name](answer, target))
        except Exception:
            return False


def finer_ok(pred, tgt):
    norm = lambda s: [v.lower().strip() for v in s.split(",")]
    want = norm(tgt)
    got = (norm(pred) + [""] * len(want))[: len(want)]
    same = lambda p, g: p == g or number(g) is not None and number(p) == number(g)
    return all(same(p, g) for p, g in zip(got, want))


def number(s):
    try:
        return float(s.replace(",", "").replace("$", ""))
    except ValueError:
        return None


def formula_ok(pred, tgt):
    return number(pred) == number(tgt) != None


def meb_ok(pred, tgt):
    pred = pred.translate(str.maketrans("×÷−–", "*/--"))
    lhs, want, ref = pred.split("=")[0], tgt.split("=")[1], tgt.split("=")[0]
    digits = lambda s: "".join(c for c in s if c not in "+-*/ ")
    return digits(lhs) == digits(ref) and abs(eval(lhs) - eval(want)) < 1e-6


def gpqa_ok(pred, tgt):
    return pred.strip("()`*. ").upper()[:1] == tgt.strip("()").upper()[:1]


CHECK = {"finer": finer_ok, "formula": formula_ok, "meb": meb_ok, "gpqa": gpqa_ok}

TASKS = {name: Task(name) for name in ("finer", "formula", "meb", "gpqa")}


def final_answer(text):
    """Строка после последнего 'FINAL ANSWER:', иначе последняя строка."""
    tail = text.rsplit("FINAL ANSWER:", 1)[-1] if "FINAL ANSWER:" in text else text.strip().rsplit("\n", 1)[-1]
    return tail.strip().split("\n")[0].strip("`*. ")


if __name__ == "__main__":
    # переигрываем старый log.json и сверяем оценку
    import sys
    task, log = TASKS[sys.argv[1]], json.load(open(sys.argv[2]))
    bad = [r["i"] for r in log if task.check(r["answer"], r["target"]) != r["correct"]]
    print(len(log), "records,", len(bad), "mismatches", bad[:10])
    sys.exit(bool(bad))
