"""Проверки задач против апстримов: finer и formula — чекеры ACE (eval/finance/data_processor.py), meb —
eval_equation_balancer DC. gpqa — наша (CHK2)."""
import pytest

from ace.tasks import TASKS, accuracy, finer_counts
from upstream import deviation, fixture

ACE = fixture("ace", "eval")
DC = fixture("dc", "evals")


@pytest.mark.parametrize("row", ACE["formula_answer_is_correct"], ids=lambda r: f"{r['pred']}|{r['target']}")
def test_formula(row):
    assert TASKS["formula"].check(row["pred"], row["target"]) is row["out"]["ok"]


@pytest.mark.parametrize("row", ACE["finer_answer_is_correct"], ids=lambda r: f"{r['pred']}|{r['target']}")
def test_finer(row):
    assert TASKS["finer"].check(row["pred"], row["target"]) is row["out"]["ok"]


@pytest.mark.parametrize("row", ACE["finer_counts"], ids=lambda r: f"{r['pred']}|{r['target']}")
def test_finer_counts(row):
    assert list(finer_counts(row["pred"], row["target"])) == row["out"]["ok"]


@pytest.mark.parametrize("task", ["finer", "formula"])
def test_accuracy(task):
    """evaluate_accuracy на тех же парах: у finer доля сущностей, у formula доля вопросов."""
    rows = ACE[f"{task}_answer_is_correct"]
    got = accuracy(TASKS[task], [r["pred"] for r in rows], [r["target"] for r in rows])
    assert got == pytest.approx(ACE[f"{task}_evaluate_accuracy"]["ok"])


def test_finer_eval_is_arithmetic_only():
    """eval апстрима — только над арифметикой; ** и имена не вычисляются (CHK1)."""
    deviation("CHK1")
    assert TASKS["finer"].check("1+1", "2") and TASKS["finer"].check("0.5", "1/2")
    assert not TASKS["finer"].check("2**3", "8")          # апстрим: True
    assert not TASKS["meb"].check("9**9**9", "9 9 9 = 1")


@pytest.mark.parametrize("row", DC["eval_equation_balancer"], ids=lambda r: r["name"])
def test_meb(row):
    assert TASKS["meb"].check(row["output"], row["target"]) is row["ok"]


def test_gpqa_is_ours():
    """eval_for_multiple_choice DC засчитывает и текст варианта; наша проверка — только буква (CHK2)."""
    deviation("CHK2")
    rows = {r["name"]: r for r in DC["eval_for_multiple_choice"]}
    same = [n for n, r in rows.items() if TASKS["gpqa"].check(r["final_answer"], r["target"]) is r["ok"]]
    assert {"exact", "letter", "lower_letter", "letter_dot", "wrong_letter", "empty", "backticks"} <= set(same)
    assert not TASKS["gpqa"].check(rows["option_text"]["final_answer"], "(B)")      # DC: True
