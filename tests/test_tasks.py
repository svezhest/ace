"""Проверки ответов задач; утилиты интерфейсов MCE в процессе стенда — на модели стенда."""
import shutil
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from types import SimpleNamespace

import pytest
from stub import Stub, embed_by_length, episode, experiment

import ablate
from ace import config
from ace.env import sandbox
from ace.loop import run
from ace.memory.mce import Folder, validate
from ace.methods import METHODS
from ace.model import Model
from ace.solver.mce import Environment
from ace.tasks import TASKS, grade, graded
from ace.upstream.mce import UTILS, signatures, task_instruction, utilities

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


def test_dapo_whole_reply():
    """verify_func TF-GRPO — math_verify по всему ответу, нестрогая: \\boxed где угодно важнее строки FINAL ANSWER,
    без него в зачёт последнее выражение (перечисление с эталоном в конце верно), равенство — по правой части;
    несколько \\boxed — множество, неверно."""
    t = TASKS["dapo"]
    assert t.check("\\boxed{4}\nFINAL ANSWER: 5", "4")
    assert t.check("x = 3 or x = 4", "4") and not t.check("x = 4 or x = 3", "4")
    assert t.check("\\boxed{r^3 - \\frac{1}{r^3} = 2786}", "2786")
    assert not t.check("\\boxed{3}, \\boxed{4}", "4")


def test_graded_by_task():
    """В зачёт у dapo и hmmt весь итоговый ответ (строка FINAL ANSWER тут не ответ), у formula — ответ решателя."""
    ep = episode(answer="7", final="so \\boxed{103}\nFINAL ANSWER: 7")
    assert grade(TASKS["dapo"], ep, "103") and grade(TASKS["hmmt"], ep, "103")
    assert graded(TASKS["formula"], ep) == "7"


def test_every_method_on_every_task(monkeypatch):
    """Метод × задача: на задаче вне таблицы вариантов (tasks.VARIANTS) метод идёт запасным вариантом стенда, а не
    падает; протокол без нужной выборки (офлайн на задаче без train / val) — понятная ошибка до обучения.
    mce (агенты Claude SDK) — только его части, зависящие от задачи."""
    monkeypatch.setattr("ace.embed.embed", embed_by_length)
    monkeypatch.setattr(config, "VAL_SIZE", 2)
    runs = 0
    for task in TASKS.values():
        task_instruction(task), signatures(task)
        Environment().prompt(experiment(task=task), Folder(), task.load()[0], 0)
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
    monkeypatch.setattr("ace.embed.embed", embed_by_length)
    monkeypatch.setattr(config, "VAL_SIZE", 2)
    for name, learner in ablate.CHAIN.items():
        if name == "mce" or name.endswith("_attempt") and not sandbox.available():
            continue
        summary = run(TASKS["formula"], learner, Stub(), 2)
        assert summary["errors"] == 0 and summary["protocol"] == learner.protocol.name, name


class Outside(BaseHTTPRequestHandler):
    """Внешний адрес: любой запрос сюда — утечка мимо модели стенда."""
    hits = []

    def do_POST(self):
        self.hits.append(self.path)
        self.send_response(500)
        self.end_headers()

    def log_message(self, *args):
        pass


class Client:
    """Заглушка клиента openai провода: пишет аргументы create, отвечает текстом."""
    def __init__(self, text):
        self.text, self.sent = text, []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kw):
        self.sent.append(kw)
        message = SimpleNamespace(content=self.text)
        return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason="stop")],
                               usage=SimpleNamespace(prompt_tokens=3, completion_tokens=2))


# response_format, который шлёт utils/llm.py апстрима (langchain ChatOpenAI.with_structured_output(TextResponse)):
# снят с его запроса
UPSTREAM_FORMAT = {"type": "json_schema", "json_schema": {
    "schema": {"description": "Simple text response from LLM.",
               "properties": {"response": {"description": "The LLM's response text", "title": "Response",
                                           "type": "string"}},
               "required": ["response"], "title": "TextResponse", "type": "object", "additionalProperties": False},
    "name": "TextResponse", "strict": True}}


def test_mce_interface_llm_on_stand_model(tmp_path, monkeypatch):
    """get_context, зовущий utils.llm апстрима, идёт в модель стенда с параметрами запроса апстрима и в её расход;
    OPENROUTER_* / OPENAI_* окружения и .env над папкой никуда не уводят."""
    srv = HTTPServer(("127.0.0.1", 0), Outside)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    outside = f"http://127.0.0.1:{srv.server_address[1]}/v1"
    for k in ("OPENROUTER_API_BASE", "OPENAI_API_BASE"):
        monkeypatch.setenv(k, outside)
    for k in ("OPENROUTER_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.setenv(k, "outside")
    for k in ("utils", "utils.llm", "utils.embedding"):
        monkeypatch.setitem(sys.modules, k, None)       # после теста — как было
    (tmp_path / ".env").write_text(f"OPENROUTER_API_BASE={outside}\nOPENROUTER_API_KEY=outside\n")
    folder = tmp_path / "iter1_sub0"
    shutil.copytree(UTILS, folder / "utils")           # копия утилит апстрима в папке, как у setup
    (folder / "interfaces").mkdir()
    (folder / "interfaces" / "__init__.py").write_text("from .get_context import get_context\n")
    (folder / "interfaces" / "get_context.py").write_text(
        "from utils.llm import call_llm\n\n\ndef get_context(symptoms):\n    return call_llm(f'Hints: {symptoms}')\n")
    model = Model(backend="wire")
    model.wire.client = Client('{"response": "check the rash"}')
    utilities(model)
    task = TASKS["symptom"]
    assert validate(folder, signatures(task)) == []
    memory = Folder()
    memory.at(None, folder)
    prompt = Environment().prompt(experiment(model, task=task), memory, dict(question="fever"), 0)
    assert "check the rash" in prompt.solver.call(None).messages[0]["content"]
    assert model.wire.client.sent == [dict(model=model.name, messages=[{"role": "user", "content": "Hints: fever"}],
                                           temperature=0.0, response_format=UPSTREAM_FORMAT)]
    assert model.usage()["calls"] == 1
    srv.shutdown()
    assert Outside.hits == []
