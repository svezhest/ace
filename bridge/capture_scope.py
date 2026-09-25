"""Эталоны SCOPE (4dc0da5): промпты, разборщики, стратегическая память, цикл on_step_complete.

Запуск из корня стенда: /Users/user/Projects/upstreams/.venvs/light/bin/python bridge/capture_scope.py
Модель — фейк через CallableModelAdapter (async, чтобы gather шёл по порядку), ответы по маркерам.
"""
import asyncio
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fake  # noqa: E402

REPO = os.path.join(fake.UPSTREAMS, "SCOPE")
sys.path.insert(0, REPO)
TMP = fake.offline()

from scope import SCOPEOptimizer, prompts  # noqa: E402
from scope.memory_optimizer import MemoryOptimizer, RuleAnalyzer, SubsumptionOptimizer  # noqa: E402
from scope.models import CallableModelAdapter, OpenAIAdapter  # noqa: E402
from scope.strategic_store import StrategicMemoryStore  # noqa: E402
from scope.synthesizer import GuidelineSynthesizer  # noqa: E402

M = "scope"
AGENT = "finer_agent"
ROLE = "Expert tagging financial entities with US GAAP XBRL tags"
TASK = "Assign the best US GAAP tag to each numeric entity"
BASE_PROMPT = "You are a financial tagging assistant. End with FINAL ANSWER: <tag>."

TEMPLATES = ["ERROR_REFLECTION_PROMPT", "QUALITY_REFLECTION_PROMPT_EFFICIENCY",
             "QUALITY_REFLECTION_PROMPT_THOROUGHNESS", "SELECTOR_PROMPT", "CLASSIFICATION_PROMPT",
             "RULE_ANALYSIS_PROMPT", "RULE_MERGE_PROMPT", "SUBSUMPTION_VERIFY_PROMPT",
             "CONFLICT_RESOLVE_PROMPT"]

# маркеры промптов
ERR = "analyzing agent execution errors"
QUAL = "analyzing agent execution quality"
SEL = "evaluating multiple candidate prompt updates"
CLS = "You are a rule classifier"
ANA = "You are a rule optimization analyzer"
MERGE = "You are merging similar rules"
SUB = "Verify if the general rule subsumes"
CONF = "You are resolving a conflict"


def norm(x):
    """Пути tmp и время — в заглушки."""
    s = json.dumps(fake._plain(x), ensure_ascii=False)
    s = s.replace(TMP, "<tmp>")
    s = re.sub(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?", "<ts>", s)
    return json.loads(s)


def adapter(llm):
    """CallableModelAdapter поверх фейка; сообщения SCOPE -> dict с плоским текстом."""
    async def fn(messages):
        msgs = []
        for m in messages:
            c = m.content
            if isinstance(c, list):
                c = "".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in c)
            msgs.append({"role": m.role, "content": c})
        return llm(msgs)
    return CallableModelAdapter(fn)


def js(obj, fence=True):
    s = json.dumps(obj)
    return f"```json\n{s}\n```" if fence else s


def snapshot(exp):
    """Файлы, которые SCOPE пишет в exp_path, с нормализацией."""
    out = {}
    for p in sorted(glob.glob(os.path.join(exp, "**", "*"), recursive=True)):
        if os.path.isfile(p):
            rel = os.path.relpath(p, exp)
            with open(p, encoding="utf-8") as f:
                txt = f.read()
            if p.endswith(".jsonl"):
                out[rel] = [json.loads(line) for line in txt.splitlines() if line.strip()]
            else:
                out[rel] = json.loads(txt)
    return norm(out)


def exp_dir(name):
    d = os.path.join(TMP, name)
    os.makedirs(d, exist_ok=True)
    return d


def between(text, start, end="\n"):
    i = text.find(start)
    if i < 0:
        return ""
    i += len(start)
    j = text.find(end, i)
    return text[i:j if j >= 0 else None]


# --- 1. промпты -------------------------------------------------------------------------------

async def capture_prompts():
    data = {"templates": {n: getattr(prompts, n) for n in TEMPLATES}}

    # синтезатор: ошибка, качество в двух режимах, выбор лучшего из двух кандидатов
    upd = {"update_text": "Check the sign of each value before tagging.",
           "rationale": "The agent confused losses with gains.", "confidence": "high"}
    primary = fake.FakeLLM([(SEL, js({"selected_index": 1, "rationale": "more general"})),
                            (ERR, js(upd)), (QUAL, js(upd))])
    cand = fake.FakeLLM([(ERR, js({**upd, "update_text": "Validate the XBRL tag against the entity type."})),
                         (QUAL, js({**upd, "update_text": "Prefer the most specific tag."}))])
    rules = [{"rule": "Always read the full sentence.", "rationale": "context"}]
    summary = "Model output: The tag is Revenues.\nObservations: Answer incorrect"
    kw = dict(agent_name=AGENT, agent_role=ROLE, task=TASK, last_step_summary=summary,
              current_system_prompt=BASE_PROMPT)
    thor = GuidelineSynthesizer(adapter(primary), use_thoroughness_mode=True)
    eff = GuidelineSynthesizer(adapter(primary), use_thoroughness_mode=False)
    bon = GuidelineSynthesizer(adapter(primary), candidate_models=[adapter(cand)], use_best_of_n=True)
    err = dict(error_type="Exception", error_message="Incorrect answer. Model answered 'Revenues', expected 'Loss'.")
    results = {
        "error": await thor.generate_update_from_error(**kw, **err, applied_rules=rules),
        "error_no_rules": await thor.generate_update_from_error(**kw, **err, applied_rules=None),
        "quality_thoroughness": await thor.generate_update_from_quality(**kw, applied_rules=rules),
        "quality_efficiency": await eff.generate_update_from_quality(**kw, applied_rules=None),
        "best_of_n_error": await bon.generate_update_from_error(**kw, **err, applied_rules=rules),
    }
    data["synthesizer"] = {"results": results, "primary_calls": primary.calls, "candidate_calls": cand.calls}

    # классификатор через SCOPEOptimizer, с одним стратегическим правилом в памяти и одним тактическим
    exp = exp_dir("prompts")
    cls = fake.FakeLLM([(CLS, js({"is_duplicate": False, "scope": "strategic", "confidence": 0.9,
                                  "domain": "data_validation", "reason": "general"}))])
    opt = SCOPEOptimizer(adapter(cls), exp_path=exp)
    await opt.strategic_store.add_strategic_rule(AGENT, "Always read the full sentence.", "context", 0.9,
                                                 "general", "t0")
    data["classification"] = {
        "result": await opt._classify_and_check_duplicate(AGENT, "Check signs.", "Losses confused.", 0.9,
                                                         [{"rule": "Tactical one.", "rationale": "r"}, "Bare string rule."]),
        "result_empty": await SCOPEOptimizer(adapter(cls), exp_path=exp_dir("prompts_empty"))
        ._classify_and_check_duplicate(AGENT, "Check signs.", "Losses confused.", 0.6, []),
        "calls": cls.calls,
    }

    # оптимизатор памяти: анализ, слияние, поглощение, конфликт
    mo = fake.FakeLLM([(ANA, js({"consolidation": [[2, 3]], "subsumption": [[0, 1]], "conflicts": [[4, 5]]})),
                       (MERGE, js({"rule": "Merged rule 2+3.", "rationale": "merged"})),
                       (SUB, js({"subsumed": True, "reason": "covered"})),
                       (CONF, js({"rule": "Resolved rule 4/5.", "rationale": "resolved"}))])
    six = [{"rule": f"Rule text {i}.", "rationale": f"why {i}", "confidence": 0.85 + i / 100} for i in range(6)]
    data["memory_optimizer"] = {"result": await MemoryOptimizer(adapter(mo)).optimize_rules(six, target_count=3),
                                "calls": mo.calls}

    # как в repro/scope_run.py: OpenAIAdapter(temperature=0) — какие параметры уходят в API
    oa = fake.FakeLLM([(ERR, js(upd))])
    openai_model = OpenAIAdapter(fake.FakeOpenAI(oa, asynchronous=True), model="ornith15-9b", temperature=0)
    await GuidelineSynthesizer(openai_model).generate_update_from_error(**kw, **err)
    data["openai_adapter_request"] = oa.calls

    # вспомогательные сериализации
    data["step_summary"] = {
        "truncate": opt._build_step_summary("x" * 250, "y" * 160, "z" * 160, truncate=True),
        "full_short": opt._build_step_summary("out", None, "obs", truncate=True),
        "no_truncate": opt._build_step_summary("x" * 250, None, None, truncate=False),
        "empty": opt._build_step_summary(None, None, None),
    }
    data["strategic_rules_text"] = opt.get_strategic_rules_for_agent(AGENT)
    return data


# --- 2. разборщики ----------------------------------------------------------------------------

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

# ответы оптимизатора/классификатора: у них свой разбор (найти ```json, потом {...}, потом ' -> ")
BLOCK_CASES = {
    "plain": '{"consolidation": [[0, 1]], "subsumption": [], "conflicts": []}',
    "fenced_json": 'Analysis:\n```json\n{"consolidation": [[0, 1]]}\n```',
    "fenced_plain": '```\n{"conflicts": [[0, 1]]}\n```',
    "garbage_around": 'I found: {"subsumption": [[0, 1]]} end',
    "single_quotes": "{'consolidation': [[0, 1]]}",
    "two_objects": '{"consolidation": [[0, 1]]} {"conflicts": [[0, 1]]}',
    "unclosed_fence": '```json\n{"consolidation": [[0, 1]]}',
    "truncated": '{"consolidation": [[0, 1]',
    "list": "[[0, 1]]",
    "empty": "",
}

CLS_CASES = {
    "full": '{"is_duplicate": false, "scope": "strategic", "confidence": 0.9, "domain": "efficiency", "reason": "ok"}',
    "fenced": '```json\n{"is_duplicate": true, "scope": "tactical", "confidence": "0.4"}\n```',
    "unknown_domain": '{"scope": "strategic", "confidence": 0.95, "domain": "finance_tags"}',
    "tactical_unknown_domain": '{"scope": "tactical", "confidence": 0.95, "domain": "finance_tags"}',
    "missing_keys": "{}",
    "garbage_around": 'Result: {"scope": "strategic", "confidence": 0.9} ok',
    "string_confidence_word": '{"scope": "strategic", "confidence": "high"}',
    "two_fences": '```json\n{"scope": "strategic"}\n```\n```json\n{"scope": "tactical"}\n```',
    "empty": "",
}


async def capture_parsers():
    syn = GuidelineSynthesizer(None)
    data = {"synthesizer._extract_json": {k: fake.call(syn._extract_json, v) for k, v in JSON_CASES.items()}}

    two = [{"rule": "Rule A.", "confidence": 0.9}, {"rule": "Rule B.", "confidence": 0.9}]
    analyzer, verify, classify = {}, {}, {}
    for k, v in BLOCK_CASES.items():
        llm = fake.FakeLLM(default=v)
        analyzer[k] = await RuleAnalyzer(adapter(llm)).analyze([dict(r) for r in two])
        sub = SubsumptionOptimizer(adapter(fake.FakeLLM(default=v.replace("consolidation", "subsumed")
                                                        .replace("[[0, 1]]", "true"))))
        verify[k] = await sub._verify_subsumption({0: two[0], 1: two[1]}, 0, 1)
    for k, v in CLS_CASES.items():
        opt = SCOPEOptimizer(adapter(fake.FakeLLM(default=v)), exp_path=exp_dir(f"parse_{k}"))
        classify[k] = await opt._classify_and_check_duplicate(AGENT, "Check signs.", "r", 0.6, [])
    data["RuleAnalyzer.analyze"] = {"inputs": BLOCK_CASES, "results": analyzer}
    data["SubsumptionOptimizer._verify_subsumption"] = {
        "note": "входы BLOCK_CASES с заменой consolidation->subsumed и [[0, 1]]->true", "results": verify}
    data["SCOPEOptimizer._classify_and_check_duplicate"] = {"inputs": CLS_CASES, "results": classify}
    return data


# --- 3. память --------------------------------------------------------------------------------

DUP_PAIRS = [
    ("Always verify the sign of values.", "always verify the sign of values."),        # регистр
    ("Verify the sign.", "Always verify the sign of every value before tagging."),     # подстрока
    ("a b c d e f g h i j", "a b c d e f g x y z"),                                    # 7/10 = 0.7, не > 0.7
    ("a b c d e f g h i j", "a b c d e f g h y z"),                                    # 8/10
    ("a b c d e f g h", "a b c d e f g h i j k l"),                                     # 8/12, делитель — большее
    ("Check units, then tag.", "check units then tag"),                                 # пунктуация мешает словам
    ("", "Anything at all."),                                                           # пустое — подстрока всего
    ("Use the period end date.", "Use the period end date."),                           # точное совпадение
    ("Tag revenue lines.", "Never guess."),                                             # разные
]


def store(name, **kw):
    return StrategicMemoryStore(exp_path=exp_dir(name), **kw)


WORDS = ["revenue", "lease", "tax", "debt", "shares", "goodwill", "inventory", "pension", "dividend",
         "warrant", "impairment", "segment"]


def rule(i, conf):
    # слова не пересекаются, иначе _is_duplicate (>70% общих слов) склеит шаблонные правила
    w = WORDS[i]
    return dict(rule_text=f"{w.title()} {w}-values need {w}-specific tags.", rationale=f"because {w}",
                confidence=conf, source_task_id=f"t{i}")


async def capture_memory():
    data = {}

    # _is_duplicate: пары в одном домене и в другом
    dup = []
    for a, b in DUP_PAIRS:
        s = store("dup")
        s.rules = {AGENT: {"general": [{"rule": a}]}}
        dup.append({"existing": a, "new": b, "same_domain": s._is_duplicate(AGENT, "general", b),
                    "other_domain": s._is_duplicate(AGENT, "efficiency", b)})
    data["_is_duplicate"] = dup

    # порог confidence в add_strategic_rule
    s = store("threshold")
    thr = {}
    for i, c in enumerate([0.5, 0.84, 0.8499999, 0.85, 0.9, 1.0]):
        thr[str(c)] = await s.add_strategic_rule(AGENT, domain="general", **rule(i, c))
    data["add_strategic_rule.threshold"] = {"added": thr, "files": snapshot(s.exp_path)}

    # порог в оптимизаторе настраивается, а в хранилище зашит 0.85
    cls = fake.FakeLLM([(CLS, js({"is_duplicate": False, "scope": "strategic", "confidence": 0.8,
                                  "domain": "general", "reason": "r"})),
                        (ERR, js({"update_text": "Double-check the period.", "rationale": "r", "confidence": 0.8}))])
    exp = exp_dir("threshold_opt")
    opt = SCOPEOptimizer(adapter(cls), exp_path=exp, strategic_confidence_threshold=0.7)
    res = await opt.on_step_complete(AGENT, ROLE, TASK, model_output="x", error=Exception("wrong"),
                                     current_system_prompt=BASE_PROMPT, task_id="t0")
    data["strategic_confidence_threshold=0.7, classifier 0.8"] = {
        "returned": res, "strategic_rules": opt.strategic_store.get_strategic_rules(AGENT),
        "files": snapshot(exp)}

    # переполнение домена без оптимизатора: усечение по confidence
    s = store("overflow_trunc", max_rules_per_domain=3)
    confs = [0.86, 0.95, 0.9, 0.99, 0.87]
    added = [await s.add_strategic_rule(AGENT, domain="general", **rule(i, c)) for i, c in enumerate(confs)]
    added.append(await s.add_strategic_rule(AGENT, domain="efficiency", **rule(9, 0.88)))
    data["overflow_truncate(max=3)"] = {"confidences": confs, "added": added, "files": snapshot(s.exp_path)}

    # переполнение с фейковым оптимизатором: 11 правил при лимите 10 -> цель int(10*0.8)=8
    mo = fake.FakeLLM([(ANA, js({"consolidation": [[0, 1]], "subsumption": [[2, 3]], "conflicts": [[4, 5]]})),
                       (MERGE, js({"rule": "Merged 0+1.", "rationale": "m"})),
                       (SUB, js({"subsumed": True})),
                       (CONF, js({"rule": "Resolved 4/5.", "rationale": "c"}))])
    s = store("overflow_opt", optimizer_model=adapter(mo))
    added = [await s.add_strategic_rule(AGENT, domain="general", **rule(i, 0.86 + i / 100)) for i in range(11)]
    data["overflow_optimize(max=10)"] = {"added": added, "files": snapshot(s.exp_path), "calls": mo.calls}

    # оптимизатор ничего не нашёл -> усечение до лимита
    idle = fake.FakeLLM([(ANA, js({"consolidation": [], "subsumption": [], "conflicts": []}))])
    s = store("overflow_idle", max_rules_per_domain=3, optimizer_model=adapter(idle))
    added = [await s.add_strategic_rule(AGENT, domain="general", **rule(i, 0.9 + i / 100)) for i in range(5)]
    data["overflow_optimizer_noop(max=3)"] = {"added": added, "files": snapshot(s.exp_path), "calls": idle.calls}

    # дубль в хранилище и дубль после перезагрузки с диска
    s = store("dup_add")
    first = await s.add_strategic_rule(AGENT, "Check the units of every value.", "r", 0.9, "general")
    again = await s.add_strategic_rule(AGENT, "check the units of every value", "r", 0.95, "general")
    other = await s.add_strategic_rule(AGENT, "check the units of every value", "r", 0.95, "efficiency")
    data["add_strategic_rule.duplicates"] = {"first": first, "same_domain": again, "other_domain": other,
                                             "files": snapshot(s.exp_path)}

    # optimize_rules: две итерации, цель 3
    mo2 = fake.FakeLLM([(lambda t: ANA in t and "Merged A" not in t,
                         js({"consolidation": [[0, 1]], "subsumption": [], "conflicts": []})),
                        (ANA, js({"consolidation": [], "subsumption": [[0, 2]], "conflicts": []})),
                        (MERGE, js({"rule": "Merged A.", "rationale": "m"})),
                        (SUB, js({"subsumed": True}))])
    five = [{"rule": f"Rule {c}.", "rationale": c, "confidence": 0.9} for c in "ABCDE"]
    data["MemoryOptimizer.optimize_rules(target=3)"] = {
        "input": [dict(r) for r in five],
        "result": await MemoryOptimizer(adapter(mo2)).optimize_rules(five, target_count=3),
        "calls": mo2.calls}

    # лимит max_rules_per_task=20: счётчик по агенту, между задачами не сбрасывается
    def synth(text):
        tid = between(text, "Error Message: task ", ".")
        return js({"update_text": f"Tactical rule from task {tid}.", "rationale": "r", "confidence": "medium"})
    llm = fake.FakeLLM([(ERR, synth), (CLS, js({"is_duplicate": False, "scope": "tactical", "confidence": 0.6,
                                                "domain": "general", "reason": "r"}))])
    opt = SCOPEOptimizer(adapter(llm), exp_path=exp_dir("limit"))
    per_task = []
    for i in range(22):
        r = await opt.on_step_complete(AGENT, ROLE, TASK, model_output="x", error=Exception(f"task {i}. wrong"),
                                       current_system_prompt=BASE_PROMPT, task_id=f"task_{i}")
        per_task.append({"task_id": f"task_{i}", "returned": r})
    other = await opt.on_step_complete("other_agent", ROLE, TASK, model_output="x", error=Exception("task 99. wrong"),
                                       current_system_prompt=BASE_PROMPT, task_id="task_99")
    data["max_rules_per_task=20 across tasks"] = {
        "per_task": per_task, "other_agent": other, "applied_rules_count": opt._applied_rules_count,
        "history": snapshot(opt.history.exp_path) if opt.history else None, "n_calls": len(llm.calls)}
    return data


# --- 4. цикл ----------------------------------------------------------------------------------

# шаги: (task_id, model_output, observations, ошибка или None)
STEPS = [
    ("finer_0", "Entity 1200 -> Revenues. FINAL ANSWER: Revenues", "Answer incorrect",
     "Incorrect answer. Model answered 'Revenues', expected 'GainLossOnSale'."),
    ("finer_1", "Entity 35 -> SharesOutstanding. FINAL ANSWER: SharesOutstanding", "Answer correct", None),
    ("finer_2", "Entity 4.5 -> InterestExpense. FINAL ANSWER: InterestExpense", "Answer incorrect",
     "Incorrect answer. Model answered 'InterestExpense', expected 'DebtInstrumentInterestRateStatedPercentage'."),
    ("finer_3", "Entity 2019 -> FiscalYear. FINAL ANSWER: FiscalYear" + " padding" * 40, "Answer correct", None),
    ("finer_4", "Entity 7 -> LeaseTerm. FINAL ANSWER: LeaseTerm", "Answer incorrect",
     "Incorrect answer. Model answered 'LeaseTerm', expected 'OperatingLeaseWeightedAverageRemainingLeaseTerm1'."),
    ("finer_5", "Entity 0.3 -> TaxRate. FINAL ANSWER: TaxRate", "Answer incorrect",
     "Incorrect answer. Model answered 'TaxRate', expected 'EffectiveIncomeTaxRateContinuingOperations'."),
    ("finer_6", "Entity 12 -> Revenues. FINAL ANSWER: Revenues", "Answer incorrect",
     "Incorrect answer. Model answered 'Revenues', expected 'GainLossOnSale'."),
]

# ответы синтезатора по ожидаемому тегу / маркеру в выводе, классификатора — по тексту правила
SYNTH = {
    "GainLossOnSale": {"update_text": "Distinguish gains and losses on sale from revenue before tagging.",
                       "rationale": "Revenue was chosen for a disposal gain.", "confidence": "high"},
    "DebtInstrumentInterestRateStatedPercentage": {
        "update_text": "Percent values next to debt terms are stated interest rates, not expenses.",
        "rationale": "A rate was tagged as an expense.", "confidence": 0.8},
    "OperatingLeaseWeightedAverageRemainingLeaseTerm1": {
        "update_text": "Prefer the most specific lease tag that matches the measure.",
        "rationale": "A generic tag was used.", "confidence": "medium"},
    "EffectiveIncomeTaxRateContinuingOperations": {
        "update_text": "Tax rate percentages map to the effective income tax rate tag.",
        "rationale": "Generic tag.", "confidence": "low"},
    "SharesOutstanding": {"update_text": "Keep the answer to a single tag on the final line.",
                          "rationale": "Output was verbose.", "confidence": 0.7},
    "FiscalYear": {"update_text": "No improvement needed", "rationale": "", "confidence": "low"},
}
CLASSIFY = {
    "Distinguish gains": {"is_duplicate": False, "scope": "strategic", "confidence": 0.92,
                          "domain": "data_validation", "reason": "general"},
    "Keep the answer": {"is_duplicate": False, "scope": "tactical", "confidence": 0.7, "domain": "general",
                        "reason": "task format"},
    "Percent values": {"is_duplicate": False, "scope": "strategic", "confidence": 0.8,
                       "domain": "analysis_methodology", "reason": "below promotion"},
    "Prefer the most specific": {"is_duplicate": False, "scope": "strategic", "confidence": 0.9,
                                 "domain": "xbrl_tags", "reason": "unknown domain"},
    "Tax rate percentages": {"is_duplicate": True, "scope": "tactical", "confidence": 0.5, "domain": "general",
                             "reason": "duplicate"},
}


def loop_llm():
    def synth(text):
        for key, upd in SYNTH.items():
            if f"expected '{key}'" in text or f"-> {key}." in text:
                return js(upd)
        return js({"update_text": "", "rationale": ""})

    def classify(text):
        upd = between(text, "Update: ")
        for key, c in CLASSIFY.items():
            if upd.startswith(key):
                return js(c)
        return "not json at all"
    return fake.FakeLLM([(CLS, classify), (ERR, synth), (QUAL, synth)])


async def run_loop(llm, exp, steps):
    """Как repro/scope_run.py: промпт растёт на каждое принятое правило."""
    opt = SCOPEOptimizer(adapter(llm), exp_path=exp, store_history=True)
    prompt = BASE_PROMPT + opt.get_strategic_rules_for_agent(AGENT)
    log = []
    for tid, out, obs, err in steps:
        n = len(llm.calls)
        res = await opt.on_step_complete(agent_name=AGENT, agent_role=ROLE, task=TASK, model_output=out,
                                         observations=obs, error=Exception(err) if err else None,
                                         current_system_prompt=prompt, task_id=tid)
        if res:
            prompt += f"\n\n## Learned Guideline:\n{res[0]}"
        log.append({"task_id": tid, "error": err, "returned": res, "calls": llm.calls[n:]})
    return opt, prompt, log


async def capture_loop():
    llm = loop_llm()
    exp = exp_dir("loop")
    opt, prompt, log = await run_loop(llm, exp, STEPS)
    first = {"steps": log, "final_prompt": prompt, "applied_rules_count": opt._applied_rules_count,
             "applied_rules_by_task": opt._applied_rules_by_task, "statistics": opt.get_statistics(),
             "files": snapshot(exp)}
    # второй прогон на том же exp_path: стратегические правила подгружаются в начальный промпт
    llm2 = loop_llm()
    opt2, prompt2, log2 = await run_loop(llm2, exp, STEPS[:2])
    second = {"initial_prompt": BASE_PROMPT + opt2.get_strategic_rules_for_agent(AGENT), "steps": log2,
              "final_prompt": prompt2, "files": snapshot(exp)}
    return {"agent": AGENT, "role": ROLE, "task": TASK, "base_prompt": BASE_PROMPT,
            "synth_replies": SYNTH, "classifier_replies": CLASSIFY, "run1": norm(first), "run2": norm(second)}


def head(funcs):
    return fake.header("SCOPE", funcs)


async def main():
    from scope import memory_optimizer, optimizer, strategic_store, synthesizer
    fake.write(M, "prompts", head({
        "prompts": prompts, "GuidelineSynthesizer.generate_update_from_error":
            synthesizer.GuidelineSynthesizer.generate_update_from_error,
        "GuidelineSynthesizer.generate_update_from_quality":
            synthesizer.GuidelineSynthesizer.generate_update_from_quality,
        "GuidelineSynthesizer._select_best_update": synthesizer.GuidelineSynthesizer._select_best_update,
        "SCOPEOptimizer._classify_and_check_duplicate": optimizer.SCOPEOptimizer._classify_and_check_duplicate,
        "SCOPEOptimizer._build_step_summary": optimizer.SCOPEOptimizer._build_step_summary,
        "MemoryOptimizer.optimize_rules": memory_optimizer.MemoryOptimizer.optimize_rules,
        "StrategicMemoryStore.get_strategic_rules_text": strategic_store.StrategicMemoryStore.get_strategic_rules_text,
        "OpenAIAdapter.generate": OpenAIAdapter.generate,
    }), norm(await capture_prompts()))
    fake.write(M, "parsers", head({
        "GuidelineSynthesizer._extract_json": synthesizer.GuidelineSynthesizer._extract_json,
        "RuleAnalyzer.analyze": RuleAnalyzer.analyze,
        "SubsumptionOptimizer._verify_subsumption": SubsumptionOptimizer._verify_subsumption,
        "SCOPEOptimizer._classify_and_check_duplicate": optimizer.SCOPEOptimizer._classify_and_check_duplicate,
    }), norm(await capture_parsers()))
    fake.write(M, "memory", head({
        "StrategicMemoryStore._is_duplicate": StrategicMemoryStore._is_duplicate,
        "StrategicMemoryStore.add_strategic_rule": StrategicMemoryStore.add_strategic_rule,
        "StrategicMemoryStore._optimize_domain_rules": StrategicMemoryStore._optimize_domain_rules,
        "StrategicMemoryStore._save_rules": StrategicMemoryStore._save_rules,
        "MemoryOptimizer.optimize_rules": MemoryOptimizer.optimize_rules,
        "SCOPEOptimizer.__init__": optimizer.SCOPEOptimizer.__init__,
        "SCOPEOptimizer._should_accept_update": optimizer.SCOPEOptimizer._should_accept_update,
    }), norm(await capture_memory()))
    fake.write(M, "loop", head({
        "SCOPEOptimizer.on_step_complete": optimizer.SCOPEOptimizer.on_step_complete,
        "CallableModelAdapter.generate": CallableModelAdapter.generate,
        "loop_as_in": "itmo/cs-masters/thesis/repro/scope_run.py:37-52",
    }), norm(await capture_loop()))


asyncio.run(main())
