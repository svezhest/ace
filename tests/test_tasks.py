"""Проверки ответов задач."""
import pytest

from ace.tasks import TASKS

MEB = TASKS["meb"]


@pytest.mark.parametrize("answer, ok", [
    ("1 + 2 + 3 = 6", True),
    ("1 * 2 * 3 = 6", True),              # засчитывается любая верная расстановка
    ("1 × 2 × 3 = 6", False),             # знаки × ÷ апстрим DC не принимает
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


@pytest.mark.parametrize("answer, ok", [("12.50", True), ("$12.5", False), ("12.51", False), ("abc", False)])
def test_formula(answer, ok):
    assert TASKS["formula"].check(answer, "12.5") is ok


def test_formula_target_not_number():
    """Нечисла апстрим ACE сравнивает строками."""
    assert TASKS["formula"].check("abc", "abc") is True


def test_finer():
    assert TASKS["finer"].check("A, b", "a,B")
    assert not TASKS["finer"].check("a", "a,b")


def test_gpqa():
    assert TASKS["gpqa"].check("(B).", "(B)")
    assert not TASKS["gpqa"].check("C", "(B)")



def test_hmmt():
    """extract_and_grade MathArena: ответ из текста решения (последний \\boxed), эталон разбирается; эталон в \\boxed{}
    (так EvoLib сверяет старое решение с ответом большинства) не разбирается — неверно."""
    t = TASKS["hmmt"]
    assert t.check("so <answer>\\boxed{103}</answer>", "103")
    assert t.check("<answer>\\boxed{\\frac{9\\sqrt{23}}{23}}</answer>", "\\frac{9 \\sqrt{23}}{23}")
    assert not t.check("x \\boxed{3375}", "\\boxed{3375}") and not t.check("\\boxed{3375}", "3376")
    assert len(t.load()) == 40 and t.load()[0]["target"] == "103"


def test_every_method_on_every_task(monkeypatch):
    """Метод × задача: на задаче вне таблицы вариантов (tasks.VARIANTS) метод идёт запасным вариантом стенда, а не
    падает; протокол без нужной выборки (офлайн на задаче без train / val) — понятная ошибка до обучения.
    mce (агенты Claude SDK) — только его части, зависящие от задачи."""
    from types import SimpleNamespace

    import numpy as np
    from stub import Stub

    from ace import config, render
    from ace.loop import run
    from ace.memory.mce import Folder, signatures
    from ace.methods import METHODS
    from ace.solver.mce import Environment
    monkeypatch.setattr("ace.embed.embed", lambda texts: np.array([[len(t) % 7 + 1.0, 1.0] for t in texts]))
    monkeypatch.setattr(config, "VAL_SIZE", 2)
    runs = 0
    for task in TASKS.values():
        render.task_instruction(task), signatures(task)
        Environment().prompt(SimpleNamespace(task=task), Folder(), task.load()[0], 0)
        for name, method in METHODS.items():
            if name == "mce":
                continue
            try:
                summary = run(task, method, Stub(), 2)
            except ValueError as error:
                assert "нужна выборка" in str(error), (name, task.name, error)
                continue
            assert summary["errors"] == 0 and summary["n"] == 2, (name, task.name)
            runs += 1
    assert runs >= 100


def test_ablation_chain_runs(monkeypatch):
    """Каждая ступень ablate.py собирается и идёт по своему протоколу на заглушке без ошибок (mce — агенты Claude SDK,
    ступени с контейнером на попытку — только при docker)."""
    import numpy as np
    from stub import Stub

    import ablate
    from ace import config
    from ace.env import sandbox
    from ace.loop import run
    monkeypatch.setattr("ace.embed.embed", lambda texts: np.array([[len(t) % 7 + 1.0, 1.0] for t in texts]))
    monkeypatch.setattr(config, "VAL_SIZE", 2)
    for name, learner in ablate.CHAIN.items():
        if name == "mce" or name.endswith("_attempt") and not sandbox.available():
            continue
        summary = run(TASKS["formula"], learner, Stub(), 2)
        assert summary["errors"] == 0 and summary["protocol"] == learner.protocol.name, name
