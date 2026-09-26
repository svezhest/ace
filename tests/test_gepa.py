"""GEPA на модели-заглушке: пул и принятие по минибатчу, откат отвергнутого, тест лучшим по val; разбор ответа
рефлексии (ProposalAdapter.parse) и разметка примеров (format_samples)."""
import json
import random
from dataclasses import replace

import pytest
from stub import TASK, Stub, right

from ace import config, parse, render, verdict
from ace.env import Sandbox
from ace.extract import Raw
from ace.learner import Learner, swap
from ace.loop import Attempts, Protocol, Version, run
from ace.memory import Lessons
from ace.methods import METHODS
from ace.methods.gepa import gepa
from ace.show import Whole
from ace.solver.gepa import Adapter
from ace.wrap.gepa import Candidate, EpochShuffled, Evolution, pareto_parent
from ace.wrap import Gate
from ace.wrap.hooks import Hooks
from ace.wrap.mce import Iterations, Meta

OFFLINE = Protocol(offline=True, epochs=2)

REFLECTION = "Your task is to write a new instruction"


def evolution(budget):
    return Evolution(gepa.inner, budget)


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
    sampler = EpochShuffled(random.Random(0))
    batches = [sampler.next(4, i, 3) for i in range(4)]
    assert all(len(b) == 3 for b in batches)
    assert sorted(batches[0] + batches[1]) != sorted(range(4)) and set(batches[0] + batches[1]) == set(range(4))


def test_pareto_parent_skips_dominated():
    """Кандидат 1 на фронте только там, где и 2, при худшем среднем — доминируем: выбора нет, кроме 0 и 2."""
    at_front = {0: {0}, 1: {1, 2}, 2: {2}}
    picks = {pareto_parent(at_front, [0.3, 0.3, 0.6], random.Random(s)) for s in range(20)}
    assert picks == {0, 2}


class RandomAdapter(Adapter):
    random = True


def test_state_of_wrapped_learner():
    """Своё состояние обёртки — в снимке и ключе ученика; при случайном показе ключа нет и у Evolution; кандидат
    хранит дамп на момент снимка — Evolution над Hooks пишет memory.json (снимок Hooks — пара)."""
    assert Evolution(swap(gepa.inner, solver=RandomAdapter(), protocol=Protocol(offline=True)), 10).key() is None
    assert evolution(10).key() == ((0, None), 0)
    hooks = Hooks(swap(METHODS["ace_stand"], protocol=Protocol(offline=True), env=Sandbox()))
    ev = Evolution(hooks, 10)
    ev.pool.append(Candidate(Version(ev.inner.snapshot(), [(True, False)], ev.inner.dump()), [None]))
    ev.take(0)
    assert ev.current == 0 and ev.dump()[-2:] == [dict(kind="candidate", id=0, memory=[], parents=[None],
                                                       scores={0: 1.0}), dict(kind="best", id=0)]


def better_model():
    """Рефлексия даёт «Better»; «Better» решает всё, seed — ничего."""
    def answer(call):
        if REFLECTION in call["user"]:
            return "```\nBetter\n```"
        return right(call) if call["system"] == "Better" else "FINAL ANSWER: 0"
    return Stub(answer)


def test_child_with_random_show_and_no_verdict():
    """Потомок — память ученика после обучения на минибатче: и при случайном показе (ключа нет), и при вердикте
    none — принятие и val по проверке задачи, а не по вердикту попытки."""
    for levels in (dict(solver=RandomAdapter()), dict(verdict=verdict.none)):
        model = better_model()
        learner = Evolution(swap(gepa.inner, **levels), 40)
        summary = run(TASK, learner, model, 3, split="val")
        assert summary["correct"] == 3 and any(c["system"] == "Better" for c in model.calls), levels


class Seen(Whole):
    """Показ, который запоминает, какой вопрос стоит в ex, когда решается item."""
    def __init__(self):
        super().__init__()
        self.mismatch = []

    def __deepcopy__(self, memo):
        return self

    def prompt(self, ex, memory, item, k):
        if ex.item is not item:
            self.mismatch.append(item["question"])
        return super().prompt(ex, memory, item, k)


class Texts(Lessons):
    """Каждое обучение добавляет «good N»."""
    def learn(self, ex, extractions):
        self.add(f"good {len(self.records())}")


class Watched(Evolution):
    def on_pass(self, ex):
        super().on_pass(ex)
        STATE.append((self.calls, len(self.pool)))


STATE = []


def test_child_question_budget_and_trace(tmp_path):
    """Потомок решает минибатч с ex.i и ex.item своего вопроса; бюджет — попытки (у группы из 3 — все три), след
    итераций — в memory.json."""
    show = Seen()
    good = Stub(lambda call: right(call) if "good" in call["system"] else "FINAL ANSWER: 0")
    inner = Learner("notes", memory=Texts(), show=show, extract=Raw(), every=3, attempts=Attempts(3),
                    protocol=Protocol(offline=True))
    val = len(TASK.load("val"))
    budget = val + 9 + 3 + val          # одна итерация: val seed, минибатч родителя, потомок на нём, val потомка
    STATE.clear()
    run(TASK, Watched(inner, budget), good, 3, str(tmp_path), split="val")
    assert show.mismatch == [] and STATE == [(budget, 2)]
    kinds = [m["kind"] for m in json.load(open(tmp_path / "memory.json"))]
    assert kinds.count("candidate") == 2 and kinds.count("iteration") == 1 and kinds[-1] == "best"


def first_minibatch(tmp_path, learner, n=10):
    """Номера train первого минибатча прогона (след итераций в memory.json)."""
    run(TASK, learner, Stub(), n, str(tmp_path), split="val")
    return [m["ids"] for m in json.load(open(tmp_path / "memory.json")) if m["kind"] == "iteration"][0]


def test_minibatch_of_swapped_learner(tmp_path):
    """swap(every=5) над Evolution: минибатч — пять вопросов, рефлексия по ним."""
    model = better_model()
    learner = swap(evolution(40), "gepa_mb5", every=5)
    run(TASK, learner, model, 10, str(tmp_path), split="val")
    reflections = [c for c in model.calls if REFLECTION in c["user"]]
    assert reflections and "# Example 5" in reflections[0]["user"] and "# Example 6" not in reflections[0]["user"]


def test_seed(tmp_path, monkeypatch):
    """Случайность Evolution — от SEED стенда, если сид не задан явно; явный сид (запись GEPA) SEED не меняет."""
    val = len(TASK.load("val"))
    budget = val + 3
    zero = first_minibatch(tmp_path / "a", evolution(budget))
    monkeypatch.setattr(config, "SEED", 1)
    assert first_minibatch(tmp_path / "b", evolution(budget)) != zero
    assert first_minibatch(tmp_path / "c", Evolution(gepa.inner, budget, 0)) == zero


def test_failed_seed_evaluation_is_logged(tmp_path):
    """Исключение в начале итерации (val seed) — запись в логе, обучение кончено, тест идёт."""
    def answer(call):
        if call["n"] == 0:
            raise RuntimeError("model 500")
        return right(call)
    summary = run(TASK, evolution(40), Stub(answer), 3, str(tmp_path), split="val")
    log = json.load(open(tmp_path / "log.json"))
    assert log[0]["phase"] == "pass" and "model 500" in log[0]["error"] and summary["n"] == 3


@pytest.mark.parametrize("make, error", [
    (lambda: Evolution(swap(METHODS["scope"], protocol=OFFLINE), 10), "на шаге"),
    (lambda: Evolution(Learner("x", protocol=OFFLINE), 10), "не учится"),
    (lambda: Evolution(swap(METHODS["ace_stand"], protocol=replace(OFFLINE, recheck=True)), 10), "recheck"),
    (lambda: Evolution(METHODS["mce_fs"], 10), "мета над метой"),
    (lambda: Meta(Gate(gepa), lambda ex, h: ""), "мета над метой"),
    (lambda: Iterations(METHODS["mce"]), "мета над метой"),
])
def test_evolution_build_errors(make, error):
    """Над учеником, где потомок не память после обучения на минибатче или бюджет не тот, и мета над метой —
    ошибка сборки, а не молчаливый холостой прогон."""
    with pytest.raises(ValueError, match=error):
        make()
