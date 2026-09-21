"""Задачи: данные, инструкция решателю и проверка ответа. Чекеры повторяют ACE, чтобы числа были сравнимы."""
import json
from dataclasses import dataclass
from pathlib import Path

DATA = Path(__file__).parent.parent / "data"


@dataclass
class Task:
    name: str
    system: str
    instr: str

    def load(self, split=""):                       # split: "" | "train" | "val"
        file = DATA / f"{self.name}{'_' + split if split else ''}{'40' if split != 'val' else '10'}.jsonl"
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

TASKS = {t.name: t for t in [
    Task("finer", "You are an XBRL expert.",
         "For each numbered entity choose the single best tag from the given list, copying it exactly. "
         "Reason briefly, then give the final answer as one line: 'FINAL ANSWER: tag1,tag2,...' "
         "(one tag per entity, in order, comma-separated, nothing else on that line)."),
    Task("formula", "You are a financial analyst.",
         "Answer the financial question using the given formula. The answer must be a plain floating point "
         "number (no units, no currency signs, no thousands separators), rounded to two decimals. "
         "Reason briefly, then give the final answer as one line: 'FINAL ANSWER: <number>'."),
    Task("meb", "You are a careful math assistant.",
         "Below is an equation with missing operators. Your task is to fill in the blanks with the correct "
         "mathematical operators: +, -, *, or /. Ensure that the equation is correct once the operators are added. "
         "The operators should be placed in the sequence they appear from left to right. Include the full equation "
         "with the operators filled in. For instance, for the equation 1 ? 2 ? 3 = 6, the correct answer is 1 + 2 + 3 = 6.\n"
         "Reason step by step, then give the final equation as one line: 'FINAL ANSWER: <equation>'."),
    Task("gpqa", "You are a careful expert in physics, chemistry and biology.",
         "Answer the multiple-choice question below. Reason carefully, then give the final answer as the "
         "option letter in parentheses on the last line after 'FINAL ANSWER:', e.g. FINAL ANSWER: (B)."),
]}


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
