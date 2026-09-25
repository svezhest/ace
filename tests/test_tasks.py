"""Проверки ответов задач и переигровка старых логов."""
import json
from pathlib import Path

import pytest

from ace.tasks import TASKS, replay

MEB = TASKS["meb"]


@pytest.mark.parametrize("answer, ok", [
    ("1 + 2 + 3 = 6", True),
    ("1 × 2 × 3 = 6", True),              # засчитывается любая верная расстановка
    ("1 + 2 * 3 = 7", False),             # значение сверяется с правой частью эталона
    ("1 - 2 + 3 = 6", False),
    ("1 + 23 = 6", False),                # числа не те
    ("(1 + 2) + 3 = 6", False),           # скобок в задаче нет
    ("1 ** 2 + 5 = 6", False),            # ** не оператор задачи и опасен для eval
    ("9**9**9", False),
    ("", False),
])
def test_meb(answer, ok):
    assert MEB.check(answer, "1 + 2 + 3 = 6") is ok


def test_meb_negative():
    assert MEB.check("19 - 8 * 28 = -205", "19 - 8 * 28 = -205")


@pytest.mark.parametrize("answer, ok", [("12.50", True), ("$12.5", True), ("12.51", False), ("abc", False)])
def test_formula(answer, ok):
    assert TASKS["formula"].check(answer, "12.5") is ok


def test_formula_target_not_number():
    assert TASKS["formula"].check("abc", "abc") is False


def test_finer():
    assert TASKS["finer"].check("A, b", "a,B")
    assert not TASKS["finer"].check("a", "a,b")


def test_gpqa():
    assert TASKS["gpqa"].check("(B).", "(B)")
    assert not TASKS["gpqa"].check("C", "(B)")


def test_replay():
    log = [dict(i=0, answer="1 + 2 + 3 = 6", target="1 + 2 + 3 = 6", correct=True),
           dict(i=1, answer="1 - 2 - 3 = 6", target="1 + 2 + 3 = 6", correct=True)]
    assert replay(MEB, log) == [1]


LOGS = sorted(Path("results").glob("*/*/log.json"))


@pytest.mark.skipif(not LOGS, reason="нет results/")
@pytest.mark.parametrize("path", LOGS, ids=str)
def test_old_logs(path):
    """Проверка судит старые прогоны так же, как тогда."""
    task = TASKS[path.parent.parent.name.rstrip("0123456789")]
    assert replay(task, json.load(path.open())) == []
