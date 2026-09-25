"""Мостик к Dynamic Cheatsheet (dynamic-cheatsheet 5cfe3c3, эталоны bridge/fixtures/dc/): шаблоны генератора,
куратора и синтеза, записанные запросы, extract_cheatsheet, вход задачи, показ пар (Dynamic_Retrieval,
FullHistoryAppending) и цикл DC-Cu / DC-RS на пяти вопросах, где наша модель отвечает ответами фейка апстрима по
порядку вызовов: каждый запрос — те же сообщения и параметры."""
import importlib
import json

import pytest
from sklearn.metrics.pairwise import cosine_similarity
from upstream import fixture

from ace import prompts
from ace.loop import Episode, Group, run
from ace.model import text_reply

DC = importlib.import_module("ace.methods.dc")       # модуль: имя в пакете занято самим методом
MEM = importlib.import_module("ace.memory.dc")
SHOW = importlib.import_module("ace.show.dc")
EXTRACT = importlib.import_module("ace.extract")
PROMPTS, PARSERS, MEMORY, LOOP = (fixture("dc", level) for level in ("prompts", "parsers", "memory", "loop"))
CU, RS = LOOP["DynamicCheatsheet_Cumulative"], LOOP["DynamicCheatsheet_RetrievalSynthesis"]


def raw(step, i):
    """Сырой вход датасета: input_txt апстрима без префикса задачи и «Question #k:»."""
    return step["input"].split(f"Question #{i + 1}:\n", 1)[1]


QUESTIONS = [raw(s, i) for i, s in enumerate(RS)]
OUTPUTS = [s["steps"][0]["generator_output"] for s in RS]       # ответ решателя фейка зависит только от вопроса


def upstream_fill(template, values):
    for k, v in values.items():
        template = template.replace(f"[[{k}]]", v)
    return template


def fake_embed(monkeypatch):
    """Векторы эталона и cosine_similarity, как у апстрима."""
    vecs = {q: v for q, v in zip(QUESTIONS, MEMORY["embeddings"])}
    monkeypatch.setattr("ace.embed.similarity", lambda texts, query: cosine_similarity([vecs[query]], [vecs[t] for t in texts])[0])

# промпты


@pytest.mark.parametrize("ours, theirs, fields", [
    ("dc_generator", "generator_prompt.txt", ["QUESTION", "CHEATSHEET"]),
    ("dc_curator", "curator_prompt_for_dc_cumulative.txt", ["QUESTION", "MODEL_ANSWER", "PREVIOUS_CHEATSHEET"]),
    ("dc_synth", "curator_prompt_for_dc_retrieval_synthesis.txt", ["PREVIOUS_INPUT_OUTPUT_PAIRS", "NEXT_INPUT", "PREVIOUS_CHEATSHEET"]),
])
def test_template(ours, theirs, fields):
    values = {f: f"<{f}> {{x}} {{{{y}}}}\nline" for f in fields}
    assert prompts.load(ours).fill(values) == upstream_fill(PROMPTS["templates"][theirs], values)


@pytest.mark.parametrize("i, task", [(0, "gpqa"), (1, "meb"), (2, "meb"), (3, "gpqa")])
def test_input(i, task):
    """Вход задачи, как его строит run_benchmark: «Question #k:», у MathEquationBalancer — вступление задачи."""
    assert SHOW.dc_input(task, i, QUESTIONS[i]) == RS[i]["input"]


class Model:
    """Отвечает записанными ответами апстрима по порядку; запоминает, что спросили."""
    name = "replay"

    def __init__(self, upstream_calls=()):
        self.upstream, self.calls = list(upstream_calls), []

    def ask(self, call):
        response = self.upstream[len(self.calls)]["response"] if len(self.calls) < len(self.upstream) else ""
        self.calls.append(dict(messages=call.messages, params=call.params))
        return text_reply(call, response)

    def usage(self):
        return dict(calls=len(self.calls), prompt_tokens=0, completion_tokens=0)


class Ex:
    task, i = None, 0

    def __init__(self, model):
        self.model = model


def request(up):
    """Запрос апстрима так, как его шлёт наш вызов: сообщения и параметры."""
    return dict(messages=up["messages"], params=dict(temperature=up["temperature"], max_completion_tokens=up["max_completion_tokens"]))


def test_cumulative_curator_request():
    """Куратор DC-Cu: тот же запрос, T = 0.0, до 2 * max_tokens; пустой cheatsheet — "(empty)"."""
    rec = PROMPTS["cumulative"]
    model = Model([rec["curator"]])
    output = rec["generator"]["response"].strip()
    ep = Episode(rec["input"], 0, SHOW.DCPrompt(input=rec["input"]), output, output, "", [], False, [], [], [])
    MEM.Cheatsheet().learn(Ex(model), [EXTRACT.Raw()(None, Group(rec["input"], [ep]), None)])
    assert model.calls == [request(rec["curator"])]


def test_synthesis_request(monkeypatch):
    """Синтез DC-RS со второго вопроса: пары в оформлении апстрима с близостью, следующий вход, прошлый cheatsheet;
    тот же запрос, до 2 * max_tokens."""
    fake_embed(monkeypatch)
    rec = PROMPTS["synthesis_with_pairs"]
    memory = MEM.Pairs(sheet=True)
    memory.add(OUTPUTS[0], question=QUESTIONS[0])
    memory.sheet.rewrite(MEM.CHEATSHEET.read(PROMPTS["synthesis_first"]["calls"][0]["response"]))
    model = Model(rec["calls"])
    SHOW.synthesis(Ex(model), memory, {"context": QUESTIONS[1]}, rec["input"])
    assert model.calls == [request(rec["calls"][0])]

# разборщик


@pytest.mark.parametrize("name", list(PARSERS["extract_cheatsheet"]))
def test_extract_cheatsheet(name):
    """extract_cheatsheet HEAD: None у нас — «оставить старый»."""
    row = PARSERS["extract_cheatsheet"][name]
    got = MEM.CHEATSHEET.read(row["input"])
    assert (row["old"] if got is None else got) == row["ok"]


def test_extract_cheatsheet_compare():
    """Строки сравнения HEAD / repro-патч / наш: наш разбор теперь совпадает с HEAD везде."""
    for name, row in fixture("dc", "cheatsheet_compare")["rows"].items():
        got = MEM.CHEATSHEET.read(row["input"])
        assert {"ok": "OLD CHEATSHEET" if got is None else got} == row["head"], name

# показ пар


def pairs_memory(n):
    m = MEM.Pairs()
    for q, out in zip(QUESTIONS[:n], OUTPUTS[:n]):
        m.add(out, question=q)
    return m


@pytest.mark.parametrize("name, k", [("Dynamic_Retrieval_top3", 3), ("Dynamic_Retrieval_top2", 2), ("FullHistoryAppending", None)])
def test_shown_pairs(monkeypatch, name, k):
    """Что стоит в [[CHEATSHEET]]: отбор top-k по близости (самая похожая последней) или все пары подряд,
    оформление как у апстрима, "(empty)" без пар."""
    fake_embed(monkeypatch)
    if k:
        monkeypatch.setattr(SHOW.RETRIEVAL, "k", k)
    sheet = SHOW.retrieval if k else SHOW.history
    for i, want in enumerate(MEMORY[name]):
        m = pairs_memory(i)
        text, recs = sheet(Ex(None), m, {"context": QUESTIONS[i]}, "")
        assert text == want["shown_cheatsheet"], (name, i)
        assert [r.question for r in recs] == want["top_k_original_inputs"], (name, i)

# цикл


class Task:
    """Пять вопросов эталона; вердикта у DC нет."""
    name, system, instr = "dc_bridge", "SYSTEM", "INSTR"

    def load(self, split="", size=None):
        return [dict(context=q, target="") for q in QUESTIONS]

    def check(self, answer, target):
        return False


def loop(monkeypatch, tmp_path, method, steps):
    """Цикл на вопросах эталона (у него задачи вперемешку: вход задачи — из эталона): вызов за вызовом тот же
    запрос, что у апстрима, и ни одного лишнего."""
    monkeypatch.setattr(SHOW, "dc_input", lambda task, i, question: steps[i]["input"])
    upstream = [c for s in steps for c in s["calls"]]
    model = Model(upstream)
    run(Task(), method, model, len(steps), str(tmp_path))
    assert model.calls == [request(c) for c in upstream]
    return json.load(open(tmp_path / "memory.json")), json.load(open(tmp_path / "log.json"))


def test_loop_cumulative(monkeypatch, tmp_path):
    memory, log = loop(monkeypatch, tmp_path, DC.dc, CU)
    assert memory == [dict(kind="sheet", id="sheet", text=CU[-1]["final_cheatsheet"])]
    assert [r["answer"] for r in log] == [s["final_answer"] for s in CU]


def test_loop_retrieval_synthesis(monkeypatch, tmp_path):
    fake_embed(monkeypatch)
    memory, log = loop(monkeypatch, tmp_path, DC.dc_rs, RS)
    assert [(r["question"], r["text"]) for r in memory if r["kind"] == "pair"] == list(zip(QUESTIONS, OUTPUTS))
    assert memory[-1] == dict(kind="sheet", id="sheet", text=RS[-1]["final_cheatsheet"])
    assert [r["answer"] for r in log] == [s["final_answer"] for s in RS]
