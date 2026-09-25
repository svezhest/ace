"""Мостик к Dynamic Cheatsheet (dynamic-cheatsheet 5cfe3c3, эталоны bridge/fixtures/dc/): шаблоны куратора и
синтеза, записанные запросы, extract_cheatsheet, показ пар (Dynamic_Retrieval, FullHistoryAppending) и цикл
DC-Cu / DC-RS на пяти вопросах, где наша модель отвечает ответами фейка апстрима по порядку вызовов."""
import copy
import importlib
import json

import numpy as np
import pytest
from upstream import deviation, fixture, messages

from ace import prompts, render
from ace.loop import Episode, Group, Prompt, run
from ace.model import Reply
from ace.show import HEAD, Scored

DC = importlib.import_module("ace.methods.dc")       # модуль: имя в пакете занято самим методом
PROMPTS, PARSERS, MEMORY, LOOP = (fixture("dc", level) for level in ("prompts", "parsers", "memory", "loop"))
CU, RS = LOOP["DynamicCheatsheet_Cumulative"], LOOP["DynamicCheatsheet_RetrievalSynthesis"]
GENERATOR = "# GENERATOR (PROBLEM SOLVER)"
MAX_TOKENS = 2048           # run_benchmark.py по умолчанию; куратор и синтез — вдвое больше


def raw(step, i):
    """Сырой вход датасета: input_txt апстрима без префикса задачи и «Question #k:» (DC2)."""
    return step["input"].split(f"Question #{i + 1}:\n", 1)[1]


QUESTIONS = [raw(s, i) for i, s in enumerate(RS)]
OUTPUTS = [s["steps"][0]["generator_output"] for s in RS]       # ответ решателя фейка зависит только от вопроса


def upstream_fill(template, values):
    for k, v in values.items():
        template = template.replace(f"[[{k}]]", v)
    return template


def as_raw(text, i, steps):
    deviation("DC2")
    return text.replace(steps[i]["input"], QUESTIONS[i])


def fake_embed(monkeypatch):
    """Готовые эмбеддинги эталона вместо BGE-M3, нормированные: скалярное произведение = cosine_similarity (DC3)."""
    deviation("DC3")
    vecs = np.array(MEMORY["embeddings"], dtype=float)
    vecs = vecs / np.linalg.norm(vecs, axis=1, keepdims=True)
    monkeypatch.setattr("ace.embed.embed", lambda texts: np.array([vecs[QUESTIONS.index(t)] for t in texts]))

# промпты


@pytest.mark.parametrize("ours, theirs, fields", [
    ("dc_curator", "curator_prompt_for_dc_cumulative.txt", ["QUESTION", "MODEL_ANSWER", "PREVIOUS_CHEATSHEET"]),
    ("dc_synth", "curator_prompt_for_dc_retrieval_synthesis.txt", ["PREVIOUS_INPUT_OUTPUT_PAIRS", "NEXT_INPUT", "PREVIOUS_CHEATSHEET"]),
])
def test_template(ours, theirs, fields):
    values = {f: f"<{f}> {{x}} {{{{y}}}}\nline" for f in fields}
    assert prompts.load(ours).fill(values) == upstream_fill(PROMPTS["templates"][theirs], values)


class Model:
    """Отвечает записанными ответами апстрима по порядку; запоминает, что спросили."""
    name = "replay"

    def __init__(self, upstream_calls=(), max_tokens=MAX_TOKENS):
        self.upstream, self.max_tokens, self.calls = list(upstream_calls), max_tokens, []

    def run(self, system, user, output=str, tools=(), deps=None, rounds=0, temperature=0, max_tokens=None, on_step=None,
            top_p=None):
        response = self.upstream[len(self.calls)]["response"] if len(self.calls) < len(self.upstream) else ""
        self.calls.append(dict(system=system, user=user, temperature=temperature, max_tokens=max_tokens or self.max_tokens))
        return Reply(response, response, False, [])

    def one(self, system, user, temperature=0, max_tokens=None):
        return self.run(system, user, temperature=temperature, max_tokens=max_tokens)

    def usage(self):
        return dict(calls=len(self.calls), prompt_tokens=0, completion_tokens=0)


class Ex:
    def __init__(self, model):
        self.model = model


def test_cumulative_curator_request():
    """Куратор DC-Cu: тот же запрос посимвольно, T = 0, до 2 * max_tokens; пустой cheatsheet — "(empty)"."""
    rec = PROMPTS["cumulative"]
    model = Model([rec["curator"]])
    DC.Cheatsheet().learn(Ex(model), [DC.Raw()(None, group(rec["input"], rec["generator"]["response"]), None)])
    call = model.calls[0]
    assert (call["system"], call["user"]) == messages(rec["curator"])
    assert call["temperature"] == rec["curator"]["temperature"] and call["max_tokens"] == rec["curator"]["max_completion_tokens"]


def group(question, output):
    """Группа из одной попытки: куратор читает вопрос и весь ответ решателя."""
    return Group(question, [Episode(question, 0, Prompt(), output, output, "", [], False, [], [], [])])


def test_synthesis_request(monkeypatch):
    """Синтез DC-RS со второго вопроса: пары в оформлении апстрима с близостью, следующий вопрос, прошлый
    cheatsheet; запрос посимвольно, до 2 * max_tokens."""
    rec = PROMPTS["synthesis_with_pairs"]
    synth = rec["calls"][0]
    vecs = np.array(MEMORY["embeddings"], dtype=float)
    sim = vecs[1] @ vecs[0] / np.linalg.norm(vecs[1]) / np.linalg.norm(vecs[0])
    pairs = render.pairs([Scored(DC.Pair("r1", OUTPUTS[0], question=QUESTIONS[0]), sim)], True, DC.NOTE)
    first = PROMPTS["synthesis_first"]["calls"][0]["response"]
    memory = DC.Pairs(sheet=True)
    memory.sheet.rewrite(DC.CHEATSHEET(first))
    fields = DC.pairs_and_sheet(pairs, memory, {"context": rec["input"]})
    assert ("", DC.SYNTH.fill(fields)) == messages(synth)
    model = Model([synth])
    DC.Synthesis(DC.retrieval, DC.SYNTH, lambda *a: fields, DC.CHEATSHEET, DC.TOKENS).prompt(Ex(model), DC.Pairs(), {}, 0)
    assert model.calls[0]["max_tokens"] == synth["max_completion_tokens"] and model.calls[0]["temperature"] == synth["temperature"]


# разборщик


@pytest.mark.parametrize("name", list(PARSERS["extract_cheatsheet"]))
def test_extract_cheatsheet(name):
    """extract_cheatsheet HEAD: None у нас — «оставить старый»."""
    row = PARSERS["extract_cheatsheet"][name]
    got = DC.CHEATSHEET(row["input"])
    assert (row["old"] if got is None else got) == row["ok"]


def test_extract_cheatsheet_compare():
    """Строки сравнения HEAD / repro-патч / наш: наш разбор теперь совпадает с HEAD везде."""
    for name, row in fixture("dc", "cheatsheet_compare")["rows"].items():
        got = DC.CHEATSHEET(row["input"])
        assert {"ok": "OLD CHEATSHEET" if got is None else got} == row["head"], name

# показ пар


def pairs_memory(n):
    m = DC.Pairs()
    for q, out in zip(QUESTIONS[:n], OUTPUTS[:n]):
        m.add(out, question=q)
    return m


def top(k):
    show = copy.copy(DC.retrieval)
    show.k = k
    return show


@pytest.mark.parametrize("name, show", [("Dynamic_Retrieval_top3", top(3)), ("Dynamic_Retrieval_top2", top(2)),
                                        ("FullHistoryAppending", DC.history)])
def test_shown_pairs(monkeypatch, name, show):
    """Что видит решатель: отбор top-k по близости (самая похожая последней) или все пары подряд, оформление
    как у апстрима, "(empty)" без пар."""
    fake_embed(monkeypatch)
    for i, want in enumerate(MEMORY[name]):
        m = pairs_memory(i)
        p = show.prompt(Ex(None), m, {"context": QUESTIONS[i]}, 0)
        assert p.system == "\n\n" + HEAD + want["shown_cheatsheet"], (name, i)
        order = [m.get(id).question for id in p.shown]
        assert order == want["top_k_original_inputs"], (name, i)

# цикл


class Task:
    """Пять вопросов эталона; вердикта у DC нет."""
    name, system, instr = "dc_bridge", "SYSTEM", "INSTR"

    def load(self, split="", size=None):
        return [dict(context=q, target="") for q in QUESTIONS]

    def check(self, answer, target):
        return False

    def accuracy(self, answers, targets):
        return 0.0


def upstream_sheet(generator_prompt):
    """То, что апстрим подставил в [[CHEATSHEET]] промпта решателя."""
    head, tail = PROMPTS["templates"]["generator_prompt.txt"].split("[[CHEATSHEET]]")
    return generator_prompt[len(head):].rsplit(tail.split("[[QUESTION]]")[0], 1)[0]


def check_loop(steps, ours):
    """Вызов за вызовом: решатель видит тот же текст памяти (DC1), куратор и синтез — тот же запрос (DC2);
    температура и бюджет те же."""
    deviation("DC1")
    calls = iter(ours)
    for i, step in enumerate(steps):
        for up in step["calls"]:
            call, (_, user) = next(calls), messages(up)
            assert call["temperature"] == up["temperature"] and call["max_tokens"] == up["max_completion_tokens"]
            if GENERATOR in user:
                assert call["user"] == render.user_message(Task.instr, QUESTIONS[i])
                assert call["system"] == Task.system + "\n\n" + HEAD + upstream_sheet(user), i
            else:
                assert (call["system"], call["user"]) == ("", as_raw(user, i, steps)), i
    assert next(calls, None) is None


def test_loop_cumulative(tmp_path):
    model = Model([c for s in CU for c in s["calls"]])
    run(Task(), DC.dc, model, len(CU), str(tmp_path))
    check_loop(CU, model.calls)
    assert json.load(open(tmp_path / "memory.json")) == [dict(kind="sheet", id="sheet", text=CU[-1]["final_cheatsheet"])]


def test_loop_retrieval_synthesis(monkeypatch, tmp_path):
    fake_embed(monkeypatch)
    model = Model([c for s in RS for c in s["calls"]])
    run(Task(), DC.dc_rs, model, len(RS), str(tmp_path))
    check_loop(RS, model.calls)
    memory = json.load(open(tmp_path / "memory.json"))
    assert [(r["question"], r["text"]) for r in memory if r["kind"] == "pair"] == list(zip(QUESTIONS, OUTPUTS))
    assert memory[-1] == dict(kind="sheet", id="sheet", text=RS[-1]["final_cheatsheet"])
