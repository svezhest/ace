"""GEPA на модели-заглушке: пул и принятие по минибатчу, откат отвергнутого, тест лучшим по val; разбор ответа
рефлексии (ProposalAdapter.parse) и разметка примеров (format_samples)."""
from stub import TASK, Stub, right

from ace import parse, render
from ace.learner import swap
from ace.loop import Protocol, run
from ace.methods.gepa import gepa
from ace.wrap.gepa import EpochShuffled, Evolution, pareto_parent

REFLECTION = "Your task is to write a new instruction"


def evolution(budget):
    return Evolution(swap(gepa.inner, protocol=Protocol(offline=True, epochs=budget)), budget)


def test_accepts_better_and_tests_best(tmp_path):
    """Потомок «Better» (верен везде, кроме первого вопроса train) принят и лучший по val; второй потомок от него
    («Worse») хуже на минибатче — отвергнут, на val не идёт; тест — лучшим."""
    reflections = []
    hard = TASK.load("train", 1)[0]["question"]

    def answer(call):
        if REFLECTION in call["user"]:
            reflections.append(call)
            return "```\nBetter\n```" if len(reflections) == 1 else "```\nWorse\n```"
        if call["system"] == "Better" and hard not in call["user"]:
            return right(call)
        return "FINAL ANSWER: 0"
    model = Stub(answer)
    val = len(TASK.load("val"))
    budget = val + 3 + 3 + val + 1          # seed, первая итерация с принятием, ещё одна
    learner = evolution(budget)
    summary = run(TASK, learner, model, 3, str(tmp_path), split="val")
    assert len(reflections) == 2 and "Better" in reflections[1]["user"]     # родитель второй — единственный на фронте
    solves = [c for c in model.calls if REFLECTION not in c["user"]]
    assert len(solves) == val + 3 + 3 + val + 3 + 3 + 3
    assert all(c["system"] == "Better" for c in solves[-3:]) and summary["correct"] == 3


def test_parse():
    assert parse.gepa_instruction("x\n```text\nnew\n```\ny") == "new"
    assert parse.gepa_instruction("```\nnew") == "new"
    assert parse.gepa_instruction("plain ```") == "plain"
    assert parse.gepa_instruction("<think> still") is None
    assert parse.gepa_instruction("<think>a</think> new") == "<think>a</think> new"


def test_samples():
    text = render.gepa_samples([{"Inputs": " q ", "Feedback": "f"}, {"Inputs": {"a": "1"}}])
    assert text == "# Example 1\n## Inputs\nq\n\n## Feedback\nf\n\n\n\n# Example 2\n## Inputs\n### a\n1\n\n"


def test_minibatches_pad_and_reshuffle():
    """Train 4 при минибатче 3: добивка самым редким до 6, новая эпоха — новое перемешивание."""
    import random
    sampler = EpochShuffled(3, random.Random(0))
    batches = [sampler.next(4, i) for i in range(4)]
    assert all(len(b) == 3 for b in batches)
    assert sorted(batches[0] + batches[1]) != sorted(range(4)) and set(batches[0] + batches[1]) == set(range(4))


def test_pareto_parent_skips_dominated():
    """Кандидат 1 на фронте только там, где и 2, при худшем среднем — доминируем: выбора нет, кроме 0 и 2."""
    import random
    at_front = {0: {0}, 1: {1, 2}, 2: {2}}
    picks = {pareto_parent(at_front, [0.3, 0.3, 0.6], random.Random(s)) for s in range(20)}
    assert picks == {0, 2}
