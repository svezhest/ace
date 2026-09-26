"""SCOPE против записей апстрима SCOPE 4dc0da5 на живой модели (bridge/live/<вариант>, run.json). Агента у SCOPE
нет: запись снята драйвером bridge/live/scope/driver.py — наша обвязка (цикл, решатель S1, formula, песочница) и
библиотека SCOPE как есть (DEVIATIONS SC2). Запись воспроизводится без модели (tools/record/replay): каждый запрос
нашего метода — агента, синтезатора, селектора, классификатора и оптимизатора домена — побайтно совпадает с
записанным, все записанные ответы востребованы; память после каждой задачи (strategic по доменам, tactical задачи,
принято за прогон), история правил (принято, отклонено, дубль) и ответы — как у апстрима.

    scope       max_rules_per_task 3 и max_strategic_rules_per_domain 3, strategic память из seed_rules.json
    scope_code  run_python; вывод исполнения берётся из записи, test_sandbox сверяет вывод нашей песочницы
    scope_bo2   Best-of-2: candidate_models — та же модель при T = 0.7
    scope_k2    два оптимизатора (efficiency, thoroughness), у каждой перспективы своя память"""
import json

import pytest

from ace import render
from ace.env import sandbox
from ace.extract.scope import Rules
from ace.learner import swap
from ace.loop import run
from ace.memory.scope import Book, Perspectives, Strategic
from ace.methods.scope import scope, scope_bo2, scope_code, scope_k2
from ace.tasks import TASKS

from . import LIVE, replay, replaying, requests

AGENT = "formula_agent"
STEPS, HISTORY = [], []         # память после каждой задачи; события правил (перспектива, текст, исход, ...)


class Watched(Perspectives):
    """Память после задачи: снимок в начале следующей (begin первой попытки) и в конце прогона (dump)."""
    started = False

    def begin(self, k):
        if k == 0 and self.started:
            STEPS.append(state(self.books))
        self.started = True
        super().begin(k)

    def dump(self):
        STEPS.append(state(self.books))
        return super().dump()


def state(books):
    return [dict(strategic={d: [(r.text, r.rationale, r.confidence) for r in rules] for d, rules in b.domains.items()},
                 tactical=[r.text for r in b.tactical], accepted=b.accepted) for b in books]


def seeded(names=("thoroughness",), **book):
    """Память с strategic правилами прошлых прогонов из seed_rules.json (как их грузит StrategicMemoryStore)."""
    memory = Watched(names, **book)
    for b in memory.books:
        for domain, rules in json.loads((LIVE / "scope" / "seed_rules.json").read_text())[AGENT].items():
            b.domains[domain] = [Strategic(b.ids.next(), r["rule"], domain, r["rationale"], r["confidence"]) for r in rules]
    return memory


METHODS = {"scope": lambda: swap(scope, memory=seeded(per_run=3, cap=3)),
           "scope_code": lambda: swap(scope_code, memory=Watched()),
           "scope_bo2": lambda: swap(scope_bo2, memory=Watched()),
           "scope_k2": lambda: swap(scope_k2, memory=Watched(("efficiency", "thoroughness")))}
RECORDED = [name for name in METHODS if (LIVE / name / "rec.jsonl").exists()]


def executed(name):
    """Код run_python -> его вывод у апстрима, из сообщений tool записанных запросов."""
    out = {}
    for request in requests(LIVE / name / "rec.jsonl"):
        msgs = request["messages"]
        calls = {c["id"]: json.loads(c["function"]["arguments"])["code"] for m in msgs for c in m.get("tool_calls") or []}
        out.update({calls[m["tool_call_id"]]: m["content"] for m in msgs if m["role"] == "tool"})
    return out


def recorded_run(ran):
    """sandbox.run по записи: stdout и stderr, из которых render.python_output соберёт записанный вывод."""
    def fake(code, *args, **kwargs):
        text = ran[code]
        head, _, err = text.partition("\n[stderr]")
        return {"stdout": head.removeprefix("[stdout]\n"), "stderr": err.removeprefix("\n"), "rc": 0, "timeout": False}
    return fake


def watch_history(patch):
    """События правил: дубль классификатора; принято или отклонено допуском (confidence, strategic ли)."""
    classify, admit = Rules.classify, Book.admit

    def classified(self, ex, proposal, book, k=0, group=None):
        x = classify(self, ex, proposal, book, k, group)
        if x is None:
            HISTORY.append((book.name, proposal.update_text, "duplicate"))
        return x

    def admitted(self, ex, text, confidence, domain, rationale):
        before = self.accepted
        admit(self, ex, text, confidence, domain, rationale)
        HISTORY.append((self.name, text, "accepted" if self.accepted > before else "rejected", confidence, domain is not None))
    patch.setattr(Rules, "classify", classified)
    patch.setattr(Book, "admit", admitted)


@pytest.fixture(scope="module", params=RECORDED)
def replayed(request, tmp_path_factory):
    name = request.param
    out = tmp_path_factory.mktemp(name)
    STEPS.clear()
    HISTORY.clear()
    with pytest.MonkeyPatch.context() as patch, replay(LIVE / name / "rec.jsonl") as srv:
        patch.setattr(sandbox, "run", recorded_run(executed(name)))
        watch_history(patch)
        learner = METHODS[name]()
        n = json.load(open(LIVE / name / "run.json"))["n"]
        run(TASKS["formula"], learner, replaying(srv), n, str(out))
    names = [b.name for b in learner.memory.books]
    return name, srv.status(), json.load(open(out / "log.json")), list(STEPS), list(HISTORY), names


def theirs_state(step):
    return [dict(strategic={d: [(r["rule"], r["rationale"], r["confidence"]) for r in rules] for d, rules in s["strategic"].items()},
                 tactical=s["tactical"], accepted=s["accepted"]) for s in step]


def test_requests(replayed):
    _, status, _, _, _, _ = replayed
    assert status["misses"] == 0 and status["unused"] == 0 and status["served"] == status["recorded"]


def test_memory(replayed):
    """Память после каждой задачи: strategic по доменам (правило, rationale, confidence), tactical задачи, принято
    за прогон (лимит без сброса между задачами)."""
    name, _, _, steps, _, _ = replayed
    assert steps == [theirs_state(s) for s in json.load(open(LIVE / name / "steps.json"))]


def test_history(replayed):
    """История правил каждой перспективы (prompt_updates апстрима): текст и исход; у не-дублей — confidence и
    strategic ли по классификатору."""
    name, _, _, _, history, names = replayed
    for n in names:
        theirs, path = [], LIVE / name / "exp" / n / "prompt_updates" / f"{AGENT}.jsonl"
        for line in (path.read_text().splitlines() if path.exists() else []):     # правил не было — файла нет
            h = json.loads(line)
            outcome = h["error_type"].split("_", 1)[1]
            theirs.append((h["update_text"], "duplicate") if outcome == "rejected_duplicate" else
                          (h["update_text"], outcome, h["confidence"], h["scope"] == "strategic"))
        assert [e[1:] for e in history if e[0] == n] == theirs


def test_answers(replayed):
    name, _, log, _, _, _ = replayed
    theirs = json.load(open(LIVE / name / "log.json"))
    assert [r["output"] for r in log] == [r["output"] for r in theirs]
    assert [(r["answer"], r["correct"]) for r in log] == [(r["answer"], r["correct"]) for r in theirs]


@pytest.mark.skipif(not sandbox.available() or "scope_code" not in RECORDED, reason="нет docker-образа песочницы или записи")
def test_sandbox():
    """Наша песочница на коде записи scope_code даёт записанный вывод."""
    ran = executed("scope_code")
    assert ran
    for code, text in ran.items():
        r = sandbox.run(code)
        assert render.python_output(r["stdout"], r["stderr"]) == text
