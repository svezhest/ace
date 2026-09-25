"""Мостик к SCOPE (4dc0da5): эталоны bridge/fixtures/scope (снятие — bridge/capture_scope.py).

Промпты — шаблоны апстрима, заполненные теми же значениями, и запросы, которые записал фейк; модель отвечает
текстом эталона; разбор ответов (parse.scope_*) — на всех входах эталона; память — дубль по словам, пороги 0.85 и
0.5, лимит 20 на агента, предел домена с оптимизатором; цикл — шаги эталона через извлечение и память SCOPE."""
import json
import re
from types import SimpleNamespace

import pytest
from upstream import deviation, fixture, messages

from ace import parse, render
from ace.extract import CONFIDENCE, DOMAIN
from ace.extract.scope import DOMAINS, Proposal, Rules, answer_step
from ace.show.scope import strategic_text
from ace.extract.scope import P as EXTRACT_P
from ace.loop import Episode, Group, Prompt
from ace.memory import Record
from ace.memory.scope import P as OPTIMIZER_P
from ace.learner import Learner
from ace.memory.scope import Book, PER_RUN, Perspectives, duplicate_words, rule_optimizer
from ace.methods.scope import scope
from ace.model import roles, text_reply

PROMPTS, PARSERS, MEMORY, LOOP = (fixture("scope", n) for n in ("prompts", "parsers", "memory", "loop"))
AGENT, ROLE = "finer_agent", "Expert tagging financial entities with US GAAP XBRL tags"
TASK = "Assign the best US GAAP tag to each numeric entity"
BASE = "You are a financial tagging assistant. End with FINAL ANSWER: <tag>."
TEMPLATES = {"ERROR_REFLECTION_PROMPT": EXTRACT_P["error"], "QUALITY_REFLECTION_PROMPT_EFFICIENCY": EXTRACT_P["efficiency"],
             "QUALITY_REFLECTION_PROMPT_THOROUGHNESS": EXTRACT_P["thoroughness"], "SELECTOR_PROMPT": EXTRACT_P["selector"],
             "CLASSIFICATION_PROMPT": EXTRACT_P["classify"], "RULE_ANALYSIS_PROMPT": OPTIMIZER_P["analyze"],
             "RULE_MERGE_PROMPT": OPTIMIZER_P["merge"], "SUBSUMPTION_VERIFY_PROMPT": OPTIMIZER_P["subsumed"],
             "CONFLICT_RESOLVE_PROMPT": OPTIMIZER_P["conflict"]}


class Model:
    """Модель-заглушка: текст ответа — reply(промпт); пишет промпты и температуру."""
    name = "stub"

    def __init__(self, reply):
        self.reply, self.calls = reply, []

    def ask(self, call):
        assert call.reader.schema is None
        _, user = roles(call.messages)
        self.calls.append(dict(user=user, temperature=call.params.get("temperature")))
        return text_reply(call, self.reply(user))


def ex(model, name="finer"):
    """Эксперимент для извлечения и памяти: агент finer_agent с ролью эталона."""
    return SimpleNamespace(model=model, task=SimpleNamespace(name=name, system=ROLE), training=True)


def user(call):
    return messages(call)[1]


MARKERS = dict(error="analyzing agent execution errors", quality="analyzing agent execution quality",
               select="evaluating multiple candidate", classify="You are a rule classifier",
               analyze="rule optimization analyzer", merge="merging similar rules", subsumed="subsumes",
               conflict="resolving a conflict")


def kind(prompt):
    return next(k for k, m in MARKERS.items() if m in prompt)


def by_kind(calls):
    """Ответ эталона по виду промпта (для вызовов, где вид однозначно задаёт ответ)."""
    answer = {}
    for c in calls:
        answer.setdefault(kind(user(c)), c["response"])
    return Model(lambda prompt: answer[kind(prompt)])


def js(obj):
    """Ответ модели как у фейка эталона: JSON в блоке ```json."""
    return f"```json\n{json.dumps(obj)}\n```"

# промпты


@pytest.mark.parametrize("name", sorted(TEMPLATES))
def test_template(name):
    """Шаблон апстрима (str.format) и наш (Jinja) на одних значениях дают один текст."""
    raw = PROMPTS["templates"][name]
    fields = set(re.findall(r"(?<!{){(\w+)(?::[^}]*)?}(?!})", raw))
    values = {f: f"<{f}> {{\"a\": [1]}}\nline 2" for f in fields}
    if "initial_confidence" in values:
        values["initial_confidence"] = 0.8765
    assert TEMPLATES[name].fill(values) == raw.format(**values)


SUMMARY = "Model output: The tag is Revenues.\nObservations: Answer incorrect"
ERROR = ("Exception", "Incorrect answer. Model answered 'Revenues', expected 'Loss'.")


def attempt(system=BASE):
    return SimpleNamespace(question=TASK, system=system)


def test_synthesizer_requests():
    """Синтезатор: ошибка с правилами и без, качество в двух перспективах, Best-of-2 — запросы как у апстрима."""
    calls, results = PROMPTS["synthesizer"]["primary_calls"], PROMPTS["synthesizer"]["results"]
    fields = dict(agent_name=AGENT, agent_role=ROLE, task=TASK, last_step_summary=SUMMARY, current_system_prompt=BASE)
    # с правилами — из наших полей (applied_rules); у нас tactical всегда и в системном промпте, это проверяет цикл
    rules = render.rules(["Always read the full sentence."])
    assert EXTRACT_P["error"].fill(fields, error_type=ERROR[0], error_message=ERROR[1], applied_rules=rules) == user(calls[0])
    assert EXTRACT_P["thoroughness"].fill(fields, applied_rules=rules) == user(calls[2])
    model = Model(lambda prompt: calls[1]["response"])
    got = [Rules().propose(ex(model), attempt(), Book(), SUMMARY, ERROR),
           Rules().propose(ex(model), attempt(), Book("efficiency"), SUMMARY, None)]
    assert [c["user"] for c in model.calls] == [user(calls[1]), user(calls[3])]
    assert [c["temperature"] for c in model.calls] == [PROMPTS["openai_adapter_request"][0]["temperature"]] * 2
    for g, key in zip(got, ["error_no_rules", "quality_efficiency"]):
        assert (g.update_text, g.rationale, g.confidence) == tuple(results[key][k] for k in ("update_text", "rationale", "confidence"))


def test_best_of_n_selector():
    """Best-of-N: кандидаты и выбор; промпт селектора из наших полей — как у апстрима. Кандидаты у нас — одна
    модель при T = 0.7 (S4)."""
    deviation("S4")
    calls = PROMPTS["synthesizer"]["primary_calls"]
    cand = PROMPTS["synthesizer"]["candidate_calls"][0]
    first = Proposal(**parse.scope_guideline(calls[4]["response"]))
    second = Proposal(**parse.scope_guideline(cand["response"]))
    selector = dict(agent_name=AGENT, agent_role=ROLE, task=TASK, current_system_prompt=BASE, issue_type="error",
                    issue_details=render.issue(SUMMARY, ERROR), candidates=render.candidates([first, second]))
    assert EXTRACT_P["selector"].fill(selector) == user(calls[5])
    answers = iter([calls[4]["response"], cand["response"], calls[5]["response"]])
    model = Model(lambda prompt: next(answers))
    best = Rules(n=2).propose(ex(model), attempt(), Book(), SUMMARY, ERROR)
    assert best.update_text == PROMPTS["synthesizer"]["results"]["best_of_n_error"]["update_text"]
    assert [c["temperature"] for c in model.calls] == [0.7, 0.7, 0]


def test_classifier_requests():
    """Классификатор: strategic из памяти и tactical попытки в контексте; пустая память."""
    c = PROMPTS["classification"]
    model = Model(lambda prompt: c["calls"][0]["response"])
    book = Book()
    book.promote(ex(model), "Always read the full sentence.", 0.9, "general", "context")
    book.tactical = [Record("t1", "Tactical one."), Record("t2", "Bare string rule.")]
    x = Rules().classify(ex(model), Proposal(update_text="Check signs.", rationale="Losses confused.", confidence=0.9), book)
    y = Rules().classify(ex(model), Proposal(update_text="Check signs.", rationale="Losses confused.", confidence=0.6), Book())
    assert [m["user"] for m in model.calls] == [user(m) for m in c["calls"]]
    for got, want in ((x, c["result"]), (y, c["result_empty"])):
        assert got.extras[CONFIDENCE] == [want["confidence"]] and got.extras[DOMAIN] == [want["domain"]]


def test_memory_optimizer_requests():
    """Оптимизатор правил: анализ, конфликт, поглощение, слияние — запросы и итог как у апстрима."""
    m = PROMPTS["memory_optimizer"]
    model = by_kind(m["calls"])
    six = [dict(rule=f"Rule text {i}.", rationale=f"why {i}", confidence=0.85 + i / 100) for i in range(6)]
    out = rule_optimizer()(model, six, 3)
    assert [c["user"] for c in model.calls] == [user(c) for c in m["calls"]]
    assert [(x["rule"], x["rationale"], x["confidence"]) for x in out] == [(x["rule"], x["rationale"], x["confidence"])
                                                                          for x in m["result"]]


@pytest.mark.parametrize("case,args", [("truncate", ("x" * 250, "y" * 160, "z" * 160)), ("full_short", ("out", "", "obs")),
                                       ("empty", ("", "", ""))])
def test_step_summary(case, args):
    """_build_step_summary с обрезкой по умолчанию (truncate_context=True); без обрезки у нас не бывает."""
    assert render.step_summary(*args) == PROMPTS["step_summary"][case]


def test_strategic_rules_text():
    book = Book()
    book.promote(ex(Model(None)), "Always read the full sentence.", 0.9, "general", "context")
    assert strategic_text(book) == PROMPTS["strategic_rules_text"]

# разбор ответов: функции апстрима в parse.py на всех входах эталона

# входы эталона _extract_json — bridge/capture_scope.py (JSON_CASES)
JSON_CASES = {
    "plain": '{"update_text": "A", "rationale": "r", "confidence": "high"}',
    "fenced_json": 'Here:\n```json\n{"update_text": "A", "rationale": "r"}\n```\nDone.',
    "fenced_plain": '```\n{"update_text": "A", "rationale": "r"}\n```',
    "two_objects": '{"update_text": "first"} and then {"update_text": "second"}',
    "two_fenced": '```json\n{"update_text": "first"}\n```\n```json\n{"update_text": "second"}\n```',
    "garbage_around": 'Sure! {"update_text": "A", "confidence": 0.9} hope this helps',
    "no_update_text_key": 'text {"rule": "A"} text',
    "truncated": '```json\n{"update_text": "A", "rationale": "cut',
    "list": '[{"update_text": "A"}]',
    "nested": 'x {"update_text": "A", "meta": {"k": 1}} y',
    "deep_nested": 'x {"update_text": "A", "meta": {"k": {"z": 1}}} y',
    "single_quotes": "{'update_text': 'A'}",
    "think_prefix": '<think>{"draft": 1}</think>{"update_text": "A"}',
    "empty": "",
}


@pytest.mark.parametrize("case", sorted(JSON_CASES))
def test_extract_json(case):
    assert parse.scope_json(JSON_CASES[case]) == PARSERS["synthesizer._extract_json"][case]["ok"]


@pytest.mark.parametrize("case", sorted(JSON_CASES))
def test_guideline_from_extract_json(case):
    """Кандидат из разобранного: .get с умолчаниями апстрима; список — сбой (.get падает)."""
    data = PARSERS["synthesizer._extract_json"][case]["ok"]
    want = (dict(update_text=data.get("update_text", ""), rationale=data.get("rationale", ""),
                 confidence=data.get("confidence", "medium")) if isinstance(data, dict) and data else None)
    assert parse.scope_guideline(JSON_CASES[case]) == want


def test_proposal_initial_confidence():
    """Метка -> 0.3 / 0.6 / 0.9, чужая метка -> 0.5, число как есть (on_step_complete)."""
    assert [Proposal(confidence=c).initial() for c in ("low", "Medium", "HIGH", "sure", 0.8, 1)] == [0.3, 0.6, 0.9, 0.5, 0.8, 1.0]


def test_quality_strips_update():
    """На качестве апстрим отдаёт правило без пробелов по краям; «none» без ошибки отбрасывается."""
    model = Model(lambda prompt: js(dict(update_text="  Keep it short.  ")))
    assert Rules().propose(ex(model), attempt(), Book(), SUMMARY, None).update_text == "Keep it short."
    model = Model(lambda prompt: js(dict(update_text=" None ")))
    assert Rules().propose(ex(model), attempt(), Book(), SUMMARY, None) is None


def test_selection():
    """_select_best_update: индекс в пределах, иначе первый; без ключа и при сбое — первый."""
    assert [parse.scope_selection(t, 2) for t in (js(dict(selected_index=1)), js(dict(selected_index=5)), '{"x": 1}',
                                                  '{"selected_index": "1"}', "junk")] == [1, 0, 0, 0, 0]


def test_analyzer_parse():
    cases = PARSERS["RuleAnalyzer.analyze"]
    for case, text in cases["inputs"].items():
        assert parse.scope_analysis(text) == cases["results"][case], case


def test_subsumption_parse():
    cases = PARSERS["SubsumptionOptimizer._verify_subsumption"]
    for case, text in PARSERS["RuleAnalyzer.analyze"]["inputs"].items():
        text = text.replace("consolidation", "subsumed").replace("[[0, 1]]", "true")
        assert parse.scope_subsumed(text) == cases["results"][case], case


KEYS = ("is_duplicate", "scope", "confidence", "domain")


def test_classifier_parse():
    """Разбор классификатора и решение нашего извлечения: дубль — правила нет; confidence и домен strategic."""
    cases = PARSERS["SCOPEOptimizer._classify_and_check_duplicate"]
    for case, text in cases["inputs"].items():
        want = cases["results"][case]
        assert {k: parse.scope_classification(text, 0.6, DOMAINS)[k] for k in KEYS} == {k: want[k] for k in KEYS}, case
        x = Rules().classify(ex(Model(lambda prompt: text)), Proposal(update_text="Check signs.", rationale="r", confidence=0.6),
                             Book())
        if want["is_duplicate"]:
            assert x is None, case
            continue
        assert x.extras[CONFIDENCE] == [want["confidence"]], case
        assert x.extras[DOMAIN] == [want["domain"] if want["scope"] == "strategic" else None], case


def test_classifier_null_confidence():
    """«confidence»: null — float(None) апстрима падает, откат на tactical с исходной confidence."""
    x = Rules().classify(ex(Model(lambda prompt: '{"scope": "strategic", "confidence": null}')),
                         Proposal(update_text="u", confidence="high"), Book())
    assert x.extras[CONFIDENCE] == [0.9] and x.extras[DOMAIN] == [None]


def test_rule_parse():
    """Слияние и конфликт: без rationale правила остаются (KeyError апстрима)."""
    assert parse.scope_rule('{"rule": "R", "rationale": "why"}') == ("R", "why")
    assert parse.scope_rule('{"rule": "R"}') is None and parse.scope_rule("[1]") is None and parse.scope_rule("") is None

# память


def rules_of(book, domain):
    return [(r.text, r.rationale, r.confidence) for r in book.domains.get(domain, [])]


def stored(files, domain):
    rules = files["strategic_memory/global_rules.json"][AGENT].get(domain, [])
    return [(r["rule"], r["rationale"], r["confidence"]) for r in rules]


WORDS = ["revenue", "lease", "tax", "debt", "shares", "goodwill", "inventory", "pension", "dividend", "warrant", "impairment",
         "segment"]


def rule(i):
    w = WORDS[i]
    return f"{w.title()} {w}-values need {w}-specific tags.", f"because {w}"


def test_is_duplicate():
    """_is_duplicate: подстрока или общих слов больше 0.7 от большего; только в своём домене."""
    for case in MEMORY["_is_duplicate"]:
        assert duplicate_words(case["new"], [case["existing"]]) == case["same_domain"], case
        book = Book()
        book.domains["general"] = [SimpleNamespace(text=case["existing"])]
        book.promote(ex(Model(None)), case["new"], 0.9, "efficiency", "r")
        assert bool(book.domains.get("efficiency")) != case["other_domain"], case


def test_strategic_threshold():
    """Порог strategic 0.85 (strategic_store.py:201): 0.8499999 нет, 0.85 да; допуск 0.5 — в tactical всё."""
    case, book = MEMORY["add_strategic_rule.threshold"], Book()
    for i, c in enumerate(case["added"]):
        book.admit(ex(Model(None)), *rule(i)[:1], float(c), "general", rule(i)[1])
    assert len(book.tactical) == len(case["added"])
    assert rules_of(book, "general") == stored(case["files"], "general")


def test_threshold_is_one_constant():
    """strategic_confidence_threshold=0.7 апстрима до хранилища не доходит: правило с 0.8 возвращается как
    strategic, но в память не попадает. У нас порог один — то же поведение, что у апстрима с порогом по умолчанию."""
    case, book = MEMORY["strategic_confidence_threshold=0.7, classifier 0.8"], Book()
    book.admit(ex(Model(None)), case["returned"][0], 0.8, "general", "r")
    assert [r.text for r in book.tactical] == [case["returned"][0]] and not book.records() and not case["strategic_rules"]




def test_overflow_truncate():
    """Сверх предела без изменений оптимизатором — усечение по confidence; домены раздельно."""
    case = MEMORY["overflow_truncate(max=3)"]
    book = Book(optimizer=lambda model, rules, target: rules, cap=3, target=2)
    for i, c in enumerate(case["confidences"]):
        book.promote(ex(Model(None)), rule(i)[0], c, "general", rule(i)[1])
    book.promote(ex(Model(None)), rule(9)[0], 0.88, "efficiency", rule(9)[1])
    assert rules_of(book, "general") == stored(case["files"], "general")
    assert rules_of(book, "efficiency") == stored(case["files"], "efficiency")


@pytest.mark.parametrize("case,cap,target,n,conf", [("overflow_optimize(max=10)", 10, 8, 11, lambda i: 0.86 + i / 100),
                                                    ("overflow_optimizer_noop(max=3)", 3, 2, 5, lambda i: 0.9 + i / 100)])
def test_overflow_optimizer(case, cap, target, n, conf):
    """Предел домена: оптимизатор до int(0.8 * предела), остаток усекается; запросы и итог как у апстрима."""
    case = MEMORY[case]
    model = by_kind(case["calls"])
    book = Book(cap=cap, target=target)
    for i in range(n):
        book.promote(ex(model), rule(i)[0], conf(i), "general", rule(i)[1])
    assert [c["user"] for c in model.calls] == [user(c) for c in case["calls"]]
    assert rules_of(book, "general") == stored(case["files"], "general")


def test_strategic_duplicates():
    case, book = MEMORY["add_strategic_rule.duplicates"], Book()
    for text, c, domain in (("Check the units of every value.", 0.9, "general"), ("check the units of every value", 0.95, "general"),
                            ("check the units of every value", 0.95, "efficiency")):
        book.promote(ex(Model(None)), text, c, domain, "r")
    assert rules_of(book, "general") == stored(case["files"], "general")
    assert rules_of(book, "efficiency") == stored(case["files"], "efficiency")


def test_optimize_rules_two_passes():
    """optimize_rules: номера правил стабильны между проходами, второй проход по оставшимся."""
    case = MEMORY["MemoryOptimizer.optimize_rules(target=3)"]
    first, second = (c["response"] for c in case["calls"] if "analyzer" in user(c))
    merge = next(c["response"] for c in case["calls"] if "merging similar" in user(c))
    subsumed = next(c["response"] for c in case["calls"] if "subsumes" in user(c))

    def reply(prompt):
        if "analyzer" in prompt:
            return second if "Merged A" in prompt else first
        return merge if "merging similar" in prompt else subsumed
    model = Model(reply)
    out = rule_optimizer()(model, [dict(x) for x in case["input"]], 3)
    assert [c["user"] for c in model.calls] == [user(c) for c in case["calls"]]
    assert [(x["rule"], x["rationale"], x["confidence"]) for x in out] == [(x["rule"], x["rationale"], x["confidence"])
                                                                          for x in case["result"]]


def test_limit_per_agent_across_tasks():
    """max_rules_per_task=20 считается на агента и между задачами не сбрасывается: задачи 21 и 22 правила не
    получают, хотя синтезатор и классификатор зовутся; у другого агента (перспективы) счётчик свой."""
    case = MEMORY["max_rules_per_task=20 across tasks"]
    task_of = re.compile(r"answered 'n(\d+)'")
    synth = js(dict(update_text="Tactical rule from task N.", rationale="r", confidence="medium"))
    classify = js(dict(is_duplicate=False, scope="tactical", confidence=0.6, domain="general", reason="r"))
    model = Model(lambda prompt: classify if kind(prompt) == "classify" else synth.replace("task N", "task " + task_of.search(prompt)[1]))
    memory = Perspectives(("thoroughness", "other"))
    learner = Learner("scope", memory=memory, show=scope.show, extract=Rules())
    got = []
    for i, k in [(i, 0) for i in range(22)] + [(99, 1)]:
        learner.prompt(ex(model), {"context": TASK}, k)
        ep = Episode(TASK, k, Prompt(), "x", "x", f"n{i}", [], False, [], [], [], ok=False, target="t", system=BASE)
        learner.on_question(ex(model), Group(TASK, [ep], target="t"))
        learner.on_batch(ex(model), [])
        got.append([r.text for r in memory.book(k).tactical] or None)
    want = [[r["returned"][0]] if r["returned"] else None for r in case["per_task"]] + [[case["other_agent"][0]]]
    assert got == want
    assert (memory.book(0).accepted, memory.book(1).accepted) == (case["applied_rules_count"][AGENT], 1)
    assert len(model.calls) == 2 * 23 == case["n_calls"]
    assert PER_RUN == 20

# цикл


def loop_model():
    """Ответы синтезатора и классификатора эталона (synth_replies, classifier_replies), как у фейка."""
    def reply(prompt):
        if kind(prompt) == "classify":
            update = prompt.split("Update: ", 1)[1].split("\n", 1)[0]
            return next((js(c) for key, c in LOOP["classifier_replies"].items() if update.startswith(key)), "not json at all")
        for key, r in LOOP["synth_replies"].items():
            if f"expected '{key}'" in prompt or f"-> {key}." in prompt:
                return js(r)
        return js(dict(update_text="", rationale=""))
    return Model(reply)


SYSTEM_BLOCK = re.compile(r"(Current system prompt \(for reference[^\n]*\n)(.*?)(\n\nAlready applied rules)", re.S)


def with_system(prompt, system):
    """Запрос апстрима с нашим текущим системным промптом: repro дописывает правила всех прошлых задач, у нас —
    strategic при запуске попытки и tactical только этой попытки (S2)."""
    return SYSTEM_BLOCK.sub(lambda m: m.group(1) + system + m.group(3), prompt)


def run_steps(learner, model, steps):
    """Шаги эталона — попытки нашего цикла: промпт попытки, эпизод с ответом и вердиктом, извлечение, память."""
    out = []
    for step in steps:
        n = len(model.calls)
        p = learner.prompt(ex(model), {"context": TASK}, 0)
        err = step["error"]
        answer, target = (re.findall(r"'([^']*)'", err) if err else ["", ""])
        out_text = LOOP_OUTPUT[step["task_id"]]
        ep = Episode(TASK, 0, p, out_text, out_text, answer, [], False, [], [], [], ok=err is None, target=target,
                     system=BASE + p.system)
        learner.on_question(ex(model), Group(TASK, [ep], target=target))
        learner.on_batch(ex(model), [])
        out.append((step, ep, model.calls[n:], [r.text for r in learner.memory.book(0).tactical]))
    return out


LOOP_OUTPUT = {"finer_0": "Entity 1200 -> Revenues. FINAL ANSWER: Revenues",
               "finer_1": "Entity 35 -> SharesOutstanding. FINAL ANSWER: SharesOutstanding",
               "finer_2": "Entity 4.5 -> InterestExpense. FINAL ANSWER: InterestExpense",
               "finer_3": "Entity 2019 -> FiscalYear. FINAL ANSWER: FiscalYear" + " padding" * 40,
               "finer_4": "Entity 7 -> LeaseTerm. FINAL ANSWER: LeaseTerm",
               "finer_5": "Entity 0.3 -> TaxRate. FINAL ANSWER: TaxRate",
               "finer_6": "Entity 12 -> Revenues. FINAL ANSWER: Revenues"}


def check_steps(done, model):
    for step, ep, calls, tactical in done:
        want = step["calls"]
        assert [kind(c["user"]) for c in calls] == [kind(user(c)) for c in want], step["task_id"]
        assert [c["response"] for c in want] == [model.reply(c["user"]) for c in calls], step["task_id"]
        # синтезатор: тип ошибки у нас по событию (SC1), системный промпт — текущий нашей попытки (S2)
        deviation("SC1", "S2")
        ours = calls[0]["user"].replace("- Error Type: IncorrectAnswer", "- Error Type: Exception")
        assert ours == with_system(user(want[0]), ep.system), step["task_id"]
        if len(want) > 1:
            assert calls[1]["user"] == user(want[1]), step["task_id"]
        assert tactical == ([step["returned"][0]] if step["returned"] else []), step["task_id"]


def test_loop():
    """Цикл эталона на 7 задачах: запросы синтезатора и классификатора, принятые правила, strategic память;
    второй прогон со strategic из первого."""
    assert answer_step(Episode(TASK, 0, Prompt(), "o", "o", "Revenues", [], False, [], [], [], ok=False,
                               target="GainLossOnSale"))[1][1] == LOOP["run1"]["steps"][0]["error"]
    model = loop_model()
    memory = Perspectives()
    learner = Learner("scope", memory=memory, show=scope.show, extract=Rules())
    done = run_steps(learner, model, LOOP["run1"]["steps"])
    check_steps(done, model)
    book = memory.book(0)
    assert book.accepted == LOOP["run1"]["applied_rules_count"][AGENT]
    # второй прогон апстрима: strategic подгружены с диска, счётчик принятых новый
    assert BASE + learner.prompt(ex(model), {"context": TASK}, 0).system == LOOP["run2"]["initial_prompt"]
    fresh = Perspectives()
    fresh.book(0).domains = book.domains
    learner2 = Learner("scope", memory=fresh, show=scope.show, extract=Rules())
    check_steps(run_steps(learner2, model, LOOP["run2"]["steps"]), model)
