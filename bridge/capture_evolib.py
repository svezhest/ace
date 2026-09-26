"""Эталоны EvoLib: промпты HMMT, разборщики utils.py, операции над библиотекой, run_iteration на 4 вопросах.

Запуск из корня стенда: $UPSTREAMS/.venvs/light/bin/python bridge/capture_evolib.py
LLMAgent и EmbeddingModel — апстримные, подменён только клиент (fake). EvoLib последователен, поэтому
разные ответы на одинаковый промпт (k_q сэмплов) выдаются по счётчику на маркер вопроса.
"""
import copy
import math
import os
import random
import sys
import types
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fake  # noqa: E402

REPO = "EvoLib"
SRC = os.path.join(fake.UPSTREAMS, REPO, "EvoLib")
sys.path.insert(0, SRC)
fake.offline()

# eval_main тянет azure при импорте — заглушка как в repro/evolib_run.py:34-45
for _name in ("azure", "azure.identity"):
    _m = types.ModuleType(_name)
    _m.__path__ = []
    sys.modules[_name] = _m
for _attr in ("AzureCliCredential", "ChainedTokenCredential",
              "ManagedIdentityCredential", "get_bearer_token_provider"):
    setattr(sys.modules["azure.identity"], _attr, lambda *a, **k: None)
sys.modules["azure"].identity = sys.modules["azure.identity"]

import numpy as np  # noqa: E402

import eval_main as em  # noqa: E402
import utils as eu  # noqa: E402
from embed import EmbeddingModel  # noqa: E402
from evolib_agent import EvoLibAgent  # noqa: E402
from llm import LLMAgent  # noqa: E402

METHOD = "evolib"


def header(funcs):
    return fake.header(REPO, funcs)


# --- клиент и модель -----------------------------------------------------------------------------

class Client:
    """OpenAI-подобный клиент над fake.FakeLLM; пишет все параметры запроса (и reasoning_effort)."""

    def __init__(self, llm, embed):
        self.llm = llm
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))
        self.embed_calls = []
        self.embeddings = SimpleNamespace(create=self._embed)
        self.embed = embed

    def _create(self, messages=None, **kw):
        reply = self.llm(messages, **kw)
        rec = self.llm.calls[-1]
        for k, v in kw.items():
            rec.setdefault(k, v)
        return fake._response(reply)

    def _embed(self, input=None, model=None, **kw):
        items = [input] if isinstance(input, str) else list(input)
        self.embed_calls.append({"model": model, "input": items})
        data = [SimpleNamespace(embedding=self.embed(s)) for s in items]
        return SimpleNamespace(data=data)


def seq(replies):
    """Ответы по кругу для одного маркера (k_q сэмплов на одинаковый промпт)."""
    state = {"i": 0}

    def reply(_text):
        r = replies[state["i"] % len(replies)]
        state["i"] += 1
        return r
    return reply


def unit(cos):
    """Вектор с заданным косинусом к [1, 0, 0]."""
    return [cos, math.sqrt(1 - cos * cos), 0.0]


def build(rules, table, reasoning=False, model="gpt-4o", **agent_kw):
    llm = fake.FakeLLM(rules, default="N/A")
    client = Client(llm, fake.TableEmbed(table))
    lm = LLMAgent(client=client, model=model, use_reasoning_api=reasoning,
                  reasoning_effort="high")
    emb = EmbeddingModel(client=client)
    agent = EvoLibAgent(
        llm=lm,
        embedder=emb,
        eval_function=agent_kw.pop("eval_function", eval_function),
        solver_prompt=em.HMMT_SOLVER_PROMPT,
        insight_generation_prompt=em.HMMT_INSIGHT_GENERATION_PROMPT,
        skill_consolidation_prompt=em.HMMT_SKILL_CONSOLIDATION_PROMPT,
        insight_consolidation_prompt=em.HMMT_INSIGHT_CONSOLIDATION_PROMPT,
        solution_comparison_prompt=em.HMMT_SOLUTION_COMPARISON_PROMPT,
        solution_extractor=em.HMMT_SOLUTION_EXTRACTOR,
        skill_extractor=em.HMMT_SKILL_EXTRACTOR,
        consolidation_similarity_threshold=0.8,  # default_threshold HMMT, eval_main.py:497
        **agent_kw,
    )
    agent.setup_state()
    return agent, llm, client


def answer_of(solution):
    import re
    m = re.findall(r"<answer>(?s:.*?)</answer>", solution or "")
    return m[-1].replace("<answer>", "").replace("</answer>", "").replace("$", "").strip() if m else None


def eval_function(solution, eval_target):
    """Наш чекер вместо matharena.extract_and_grade: сравнение ответа в <answer> со строкой-целью."""
    if eval_target is None:
        return -1, None
    ok = answer_of(solution) == str(eval_target)
    return (1 if ok else 0), None


def eval_function_gold(solution, eval_target):
    """Как в repro «gold»: непустой test_result переводит агента в ветку с проверкой."""
    if eval_target is None:
        return -1, None
    got = answer_of(solution)
    ok = got == str(eval_target)
    return (1 if ok else 0), {"correct": ok, "answer": got, "expected": eval_target}


def lib(agent):
    return {"skill_lib": agent.skill_lib, "insight_lib": agent.insight_lib}


def solution(desc, result, answer):
    return (f"<subtask>\n<description>\n{desc}\n</description>\n<solution>\nwork\n</solution>\n"
            f"<result>{result}</result>\n</subtask>\n<answer>{answer}</answer>")


# --- 1. промпты ----------------------------------------------------------------------------------

def capture_prompts():
    problem = "Compute 2+3."
    skills = [solution("Add two integers a and b.", "5", "5")]
    insights = ["If adding integers, then do check the carry."]
    sol1, sol2 = solution("Add 2 and 3.", "5", "5"), solution("Add 2 and 3.", "6", "6")
    filled = {
        "solver_empty": em.HMMT_SOLVER_PROMPT(problem, [], []),
        "solver_skills": em.HMMT_SOLVER_PROMPT(problem, skills, []),
        "solver_insights": em.HMMT_SOLVER_PROMPT(problem, [], insights),
        "solver_both_skills_win": em.HMMT_SOLVER_PROMPT(problem, skills, insights),
        "insight_generation": em.HMMT_INSIGHT_GENERATION_PROMPT(problem, sol1, None),
        "insight_generation_with_test_result": em.HMMT_INSIGHT_GENERATION_PROMPT(
            problem, sol1, {"correct": False}),
        "skill_consolidation": em.HMMT_SKILL_CONSOLIDATION_PROMPT([sol1, sol2]),
        "insight_consolidation": em.HMMT_INSIGHT_CONSOLIDATION_PROMPT(
            insights + ["If adding decimals, then do align the point."]),
        "solution_comparison": em.HMMT_SOLUTION_COMPARISON_PROMPT(problem, sol1, sol2),
    }
    # параметры запроса LLMAgent: HMMT по умолчанию o4-mini через reasoning API (eval_main.py:494-496)
    requests = {}
    for name, reasoning, model in [("reasoning_o4-mini", True, "o4-mini"), ("chat_gpt-4o", False, "gpt-4o")]:
        agent, llm, _ = build([("", "ok")], {}, reasoning=reasoning, model=model)
        agent.llm.generate("hello", temperature=0, top_p=0.5)
        rec = dict(llm.calls[-1])
        requests[name] = rec
    raw = {
        "HMMT_INSTRUCTION_PROMPT": em.HMMT_INSTRUCTION_PROMPT,
        "HMMT_FORMAT_PROMPT": em.HMMT_FORMAT_PROMPT,
    }
    head = header({
        "HMMT_SOLVER_PROMPT": em.HMMT_SOLVER_PROMPT,
        "HMMT_INSIGHT_GENERATION_PROMPT": em.HMMT_INSIGHT_GENERATION_PROMPT,
        "HMMT_SKILL_CONSOLIDATION_PROMPT": em.HMMT_SKILL_CONSOLIDATION_PROMPT,
        "HMMT_INSIGHT_CONSOLIDATION_PROMPT": em._insight_consolidation_prompt,
        "HMMT_SOLUTION_COMPARISON_PROMPT": em.HMMT_SOLUTION_COMPARISON_PROMPT,
        "LLMAgent.generate": LLMAgent.generate,
    })
    fake.write(METHOD, "prompts", head, {"raw": raw, "filled": filled, "requests": requests})


# --- 2. разборщики -------------------------------------------------------------------------------

def capture_parsers():
    sub = solution("Add a and b.", "5", "5")
    subtasks_inputs = {
        "one": sub,
        "two": sub + "\n" + solution("Multiply a and b.", "6", "6"),
        "no_close": "<subtask>\n<description>x</description>\n",
        "no_description": "<subtask>\n<solution>y</solution>\n</subtask>",
        "one_without_description_among_two": sub + "\n<subtask>no desc</subtask>",
        "two_descriptions": "<subtask><description> a </description><description>b</description></subtask>",
        "upper_case": "<SUBTASK><description>x</description></SUBTASK>",
        "nested": "<subtask><subtask><description>in</description></subtask></subtask>",
        "empty": "",
    }
    fenced_inputs = {
        "one": "```insights\nIf a, then b.\n```",
        "two": "```insights\nIf a, then b.\n```\ntext\n```insights\nIf c, then d.\n```",
        "no_close": "```insights\nIf a, then b.\n",
        "upper_case": "```INSIGHTS\nIf a, then b.\n```",
        "other_tag_between": "```python\nx=1\n```\n```insights\nIf a, then b.\n```",
        "tag_prefix": "```insightsx\nIf a, then b.\n```",
        "inner_fence": "```insights\nIf a, then use ```code```.\n```",
        "empty": "",
    }
    first_inputs = {k: v for k, v in fenced_inputs.items()}
    first_inputs["judgment"] = "```judgment\nSolution 2 is better.\n```"
    if_inputs = {
        "normal": "If the sum is odd, then do check parity.",
        "two_then": "If a, then b, then c.",
        "no_then": "If a and b.",
        "lower_if": "if a, then b.",
        "if_inside": "If x, then If y.",
        "then_without_comma": "If a then b.",
        "empty": "",
    }
    code = ("import os\n\ndef add(a, b):\n    \"\"\"Add two numbers.\"\"\"\n    return a + b\n\n"
            "def main():\n    \"\"\"Entry.\"\"\"\n    print(add(1, 2))\n")
    functions_inputs = {
        "normal": (code, ["main"]),
        "no_exclude": (code, None),
        "one_without_docstring": (code + "\ndef mul(a, b):\n    return a * b\n", ["main"]),
        "nested_def": ("def outer():\n    \"\"\"Outer.\"\"\"\n    def inner():\n        return 1\n    return inner()\n", None),
        "async": ("async def f():\n    \"\"\"Async.\"\"\"\n    return 1\n", None),
        "class_method": ("class A:\n    def m(self):\n        \"\"\"M.\"\"\"\n        return 1\n", None),
        "empty_docstring": ("def f():\n    \"\"\"   \"\"\"\n    return 1\n", None),
        "syntax_error": ("def f(:\n  pass\n", None),
        "empty": ("", None),
    }
    data = {
        "extract_subtasks": {k: fake.call(eu.extract_subtasks, v) for k, v in subtasks_inputs.items()},
        "extract_fenced_blocks": {k: fake.call(eu.extract_fenced_blocks, v, "insights")
                                  for k, v in fenced_inputs.items()},
        "extract_first_fenced_block": {k: fake.call(eu.extract_first_fenced_block, v,
                                                    "judgment" if k == "judgment" else "insights")
                                       for k, v in first_inputs.items()},
        "extract_if_condition": {k: fake.call(eu.extract_if_condition, v) for k, v in if_inputs.items()},
        "extract_functions": {k: fake.call(eu.extract_functions, c, ex) for k, (c, ex) in functions_inputs.items()},
        "extract_function_name": {k: fake.call(eu.extract_function_name, v) for k, v in {
            "def": "def add(a, b):\n    return a", "async": "async def f(x):", "no_paren": "x = 1"}.items()},
        "HMMT_SOLUTION_EXTRACTOR": fake.call(em.HMMT_SOLUTION_EXTRACTOR, sub, "prefix"),
        "BIGCODE_SOLUTION_EXTRACTOR": {
            "fenced": fake.call(em.BIGCODE_SOLUTION_EXTRACTOR, "```python\nx=1\n```", "import os"),
            "none": fake.call(em.BIGCODE_SOLUTION_EXTRACTOR, "x=1", "import os")},
        "CODE_SKILL_EXTRACTOR": fake.call(em.CODE_SKILL_EXTRACTOR, "```python\n" + code + "```"),
    }

    # разбор ответов модели внутри агента: generate_insight, consolidate_insights, is_better_solution
    insight_replies = {
        "fenced": "```insight\nIf a, then b.\n```",
        "tag": "<mistake>m</mistake>\n<insight>\nIf a, then b.\n</insight>",
        "tag_and_fenced": "<insight>If tag, then t.</insight>\n```insight\nIf fenced, then f.\n```",
        "two_tags": "<insight>If one, then 1.</insight><insight>If two, then 2.</insight>",
        "na": "<insight>\nN/A\n</insight>",
        "na_with_text": "<insight>N/A, I agree</insight>",
        "upper_tag": "<INSIGHT>If a, then b.</INSIGHT>",
        "no_close": "<insight>If a, then b.",
        "empty_fenced_then_tag": "```insight\n```\n<insight>If a, then b.</insight>",
    }
    gi = {}
    for k, r in insight_replies.items():
        agent, _, _ = build([("", r)], {})
        gi[k] = fake.call(agent.generate_insight, "P", "S", None)
    consol_replies = {
        "two_lines": "```insights\nIf a, then b.\nIf c, then d.\n```",
        "numbered": "```insights\n1. If a, then b.\n- If c, then d.\n```",
        "indented": "```insights\n   If a, then b.\n```",
        "lower_if": "```insights\nif a, then b.\n```",
        "multiline_insight": "```insights\nIf a,\nthen b.\n```",
        "no_fence": "If a, then b.",
        "two_fences": "```insights\nIf a, then b.\n```\n```insights\nIf c, then d.\n```",
    }
    ci = {}
    for k, r in consol_replies.items():
        agent, _, _ = build([("", r)], {})
        ci[k] = fake.call(agent.consolidate_insights, ["If x, then y.", "If x, then z."])
    judgment_replies = {
        "sol2": "```judgment\nSolution 2 is better.\n```",
        "sol1": "```judgment\nSolution 1 is better.\n```",
        "sol2_lower": "```judgment\nsolution 2 is better\n```",
        "no_fence": "Solution 2 is better.",
        "sol1_mentions_sol2": "```judgment\nSolution 1 is better than solution 2.\n```",
    }
    jb = {}
    for k, r in judgment_replies.items():
        agent, _, _ = build([("", r)], {})
        jb[k] = fake.call(agent.is_better_solution, "P", "S1", "S2")
    data["EvoLibAgent.generate_insight"] = gi
    data["EvoLibAgent.consolidate_insights"] = ci
    data["EvoLibAgent.is_better_solution"] = jb

    head = header({
        "extract_subtasks": eu.extract_subtasks,
        "extract_fenced_blocks": eu.extract_fenced_blocks,
        "extract_first_fenced_block": eu.extract_first_fenced_block,
        "extract_if_condition": eu.extract_if_condition,
        "extract_functions": eu.extract_functions,
        "extract_function_name": eu.extract_function_name,
        "generate_insight": EvoLibAgent.generate_insight,
        "consolidate_insights": EvoLibAgent.consolidate_insights,
        "is_better_solution": EvoLibAgent.is_better_solution,
    })
    fake.write(METHOD, "parsers", head, data)


# --- 3. память -----------------------------------------------------------------------------------

class ChoicesSpy:
    """Пишет веса random.choices и отдаёт выбор оригиналу."""

    def __init__(self):
        self.orig = random.choices
        self.log = []

    def __call__(self, population, weights=None, k=1, **kw):
        out = self.orig(population, weights=weights, k=k, **kw)
        self.log.append({"population": list(population), "weights": [float(w) for w in weights],
                         "k": k, "chosen": out})
        return out


def sample_cases():
    spy = ChoicesSpy()
    random.choices = spy
    rnd_orig = random.random
    last = {}

    def rnd():
        last["p"] = rnd_orig()
        return last["p"]
    random.random = rnd
    skill_lib = {
        "skill_high": [0.7, [0.2, 0.4], "d1", [1, 0, 0]],
        "skill_negative_ig": [-0.3, [], "d2", [1, 0, 0]],
        "skill_zero": [0.0, [0.0], "d3", [1, 0, 0]],
    }
    insight_lib = {
        "If a, then b.": [[0.5, 0.1], [1, 0, 0]],
        "If c, then d.": [[], [1, 0, 0]],
        "If e, then f.": [[-1.0], [1, 0, 0]],
    }
    cases = {
        "both": (skill_lib, insight_lib, {}),
        "skills_only": (skill_lib, {}, {}),
        "insights_only": ({}, insight_lib, {}),
        "empty": ({}, {}, {}),
        "w_IG_100": (skill_lib, insight_lib, {"w_IG": 100.0}),
        "k_sample_2": (skill_lib, insight_lib, {"k_sample_skills": 2, "k_sample_insights": 2}),
    }
    out = {}
    try:
        for name, (sl, il, kw) in cases.items():
            runs = []
            for seed in range(10):
                agent, _, _ = build([], {}, **kw)
                agent.load_state({k: [v[0], list(v[1]), v[2], v[3]] for k, v in sl.items()},
                                 {k: [list(v[0]), v[1]] for k, v in il.items()})
                random.seed(seed)
                spy.log.clear()
                skills, insights = agent._sample_from_library()
                runs.append({"seed": seed, "p_choice": last["p"], "skills": skills,
                             "insights": insights, "choices": list(spy.log)})
            out[name] = runs
    finally:
        random.choices = spy.orig
        random.random = rnd_orig
    return out


def ig_cases():
    agent, _, _ = build([], {})
    cases = {
        "majority_2_of_3": (1.0, [1.0, 1.0, 0.0]),
        "all_right": (1.0, [1.0, 1.0, 1.0]),
        "all_wrong": (0.0, [0.0, 0.0, 0.0]),
        "one_of_3": (1.0, [1.0, 0.0, 0.0]),
        "halved": (0.5, [0.5, 0.5, 0.0]),
        "tiny_mean": (1.0, [0.01, 0.0, 0.0]),
        "single": (1.0, [1.0]),
    }
    return {k: {"best": b, "scores": s, "IG": agent.compute_IG(b, s)} for k, (b, s) in cases.items()}


def future_ig_cases():
    out = {}
    agent, _, _ = build([], {})
    agent.load_state(
        {"s1": [0.1, [], "d", [1, 0, 0]], "s2": [0.1, [0.3], "d", [1, 0, 0]]},
        {"i1": [[], [1, 0, 0]], "i2": [[0.2], [1, 0, 0]]},
    )
    steps = [
        # best_score, best_sample, score_list, sample_list
        ("in_best_and_one_other", 1.0, ["s1", "i1"], [1.0, 0.0, 0.0], [["s1", "i1"], ["s1", "i1"], []]),
        ("in_all_samples", 1.0, ["s1", "i1"], [1.0, 1.0], [["s1", "i1"], ["s1", "i1"]]),
        ("missing_from_lib", 1.0, ["gone"], [1.0, 0.0], [["gone"], []]),
        ("baseline_zero_eps", 0.5, ["s2", "i2"], [0.5, 0.0, 0.0], [["s2", "i2"], [], []]),
        ("duplicates_in_best", 1.0, ["s1", "s1", "i1", "i1"], [1.0, 0.0], [["s1", "i1"], []]),
    ]
    for name, best, sample, scores, samples in steps:
        agent.update_future_IG_for_skills(best, [x for x in sample if x.startswith("s") or x == "gone"],
                                          scores, samples)
        agent.update_future_IG_for_insights(best, [x for x in sample if x.startswith("i") or x == "gone"],
                                            scores, samples)
        out[name] = {"best": best, "best_sample": sample, "scores": scores, "samples": samples,
                     "after": copy.deepcopy({k: v[1] for k, v in agent.skill_lib.items()} |
                                            {k: v[0] for k, v in agent.insight_lib.items()})}
    return out


def insight_cases():
    """add_new_insight: эмбеддинг берётся от условия (до ', then '), порог 0.8 строгий."""
    table = [
        ("base cond", unit(1.0)),
        ("near cond", unit(0.81)),
        ("far cond", unit(0.79)),
        ("edge cond", unit(0.8)),
        ("merged cond", unit(0.95)),
        ("other merged", [0.0, 1.0, 0.0]),
    ]
    replies = {
        "merge_to_one": "```insights\nIf merged cond, then do both.\n```",
        "merge_to_two": "```insights\nIf merged cond, then do one.\nIf other merged, then do two.\n```",
        "merge_to_zero": "no fenced block",
        "merge_keeps_old": "```insights\nIf base cond, then do x.\nIf near cond, then do y.\n```",
    }
    out = {}
    base = "If base cond, then do x."
    for name, new, reply in [
        ("into_empty", None, None),
        ("below_079", "If far cond, then do y.", None),
        ("exactly_080", "If edge cond, then do y.", None),
        ("above_081_merge_to_one", "If near cond, then do y.", replies["merge_to_one"]),
        ("above_081_merge_to_two", "If near cond, then do y.", replies["merge_to_two"]),
        ("above_081_merge_to_zero", "If near cond, then do y.", replies["merge_to_zero"]),
        ("above_081_merge_keeps_old", "If near cond, then do y.", replies["merge_keeps_old"]),
        ("empty_insight", "", None),
        ("same_text_again", base, replies["merge_to_one"]),
    ]:
        agent, llm, client = build([("consolidate these insights", reply or "")], table)
        agent.add_new_insight(base)
        agent.insight_lib[base][0].extend([0.4, 0.2])  # будущий IG старого, чтобы видеть наследование
        before = {k: list(v[0]) for k, v in agent.insight_lib.items()}
        if new is not None:
            agent.add_new_insight(new)
        out[name] = {"new": new, "before": before, "after": agent.insight_lib,
                     "embedded": [c["input"] for c in client.embed_calls],
                     "llm_prompts": [c["messages"][0]["content"] for c in llm.calls]}
    return out


def skill_cases():
    """add_new_skills: эмбеддинг по описанию подзадачи, слияние усредняет IG с IG_update_rate."""
    table = [
        ("Base desc", unit(1.0)),
        ("Near desc", unit(0.81)),
        ("Far desc", unit(0.79)),
        ("Merged desc", unit(0.97)),
        ("Split desc", [0.0, 1.0, 0.0]),
    ]
    base = eu.extract_subtasks(solution("Base desc.", "1", "1"))
    near = eu.extract_subtasks(solution("Near desc.", "2", "2"))
    far = eu.extract_subtasks(solution("Far desc.", "3", "3"))
    merged = solution("Merged desc.", "4", "4")
    split = solution("Merged desc.", "4", "4") + "\n" + solution("Split desc.", "5", "5")
    out = {}
    for name, new, ig, reply in [
        ("into_empty", [], 0.0, ""),
        ("below_079", far, 0.3, ""),
        ("above_081_merge_to_one", near, 0.3, merged),
        ("above_081_merge_to_two", near, 0.3, split),
        ("above_081_merge_to_zero", near, 0.3, "no subtasks"),
        ("batch_near_and_far", near + far, 0.3, merged),
        ("two_similar_in_one_batch", near + eu.extract_subtasks(solution("Near desc again.", "6", "6")),
         0.3, merged),
    ]:
        agent, llm, client = build([("consolidate these example problems", reply)], table)
        agent.add_new_skills(base, 0.9)
        agent.skill_lib[base[0][0]][1].extend([0.5])
        before = {k: [v[0], list(v[1])] for k, v in agent.skill_lib.items()}
        agent.add_new_skills(new, ig)
        out[name] = {"new": new, "IG_score": ig, "before": before, "after": agent.skill_lib,
                     "embedded": [c["input"] for c in client.embed_calls],
                     "llm_calls": len(llm.calls)}
    return out


def majority_cases():
    """run_iteration без эталона: большинство по <answer>, штраф ×0.5 при непустом инсайте."""
    ok = "If sums are small, then do add digits."
    cases = {
        # имя: (ответы k_q сэмплов, ответ генерации инсайта, eval_target, prev_best_solution, судья)
        "2_of_3_insight": (["5", "5", "6"], f"<insight>{ok}</insight>", None, "", None),
        "2_of_3_insight_na": (["5", "5", "6"], "<insight>N/A</insight>", None, "", None),
        "all_differ": (["4", "5", "6"], f"<insight>{ok}</insight>", None, "", None),
        "dollar_stripped": (["$5$", "5", "6"], f"<insight>{ok}</insight>", None, "", None),
        "whitespace_differs": (["5", " 5 ", "5.0"], f"<insight>{ok}</insight>", None, "", None),
        "no_answer_tags": ([None, None, None], f"<insight>{ok}</insight>", None, "", None),
        "one_answer_only": (["5", None, None], f"<insight>{ok}</insight>", None, "", None),
        "prev_best_not_improving_judge_2": (["5", "5", "6"], "<insight>N/A</insight>", "5",
                                            solution("Old.", "7", "7"),
                                            "```judgment\nSolution 2 is better.\n```"),
        "prev_best_not_improving_judge_1": (["5", "5", "6"], "<insight>N/A</insight>", "5",
                                            solution("Old.", "7", "7"),
                                            "```judgment\nSolution 1 is better.\n```"),
        "prev_best_agrees_with_majority": (["5", "5", "6"], "<insight>N/A</insight>", "5",
                                           solution("Old.", "5", "5"),
                                           "```judgment\nSolution 2 is better.\n```"),
    }
    out = {}
    for name, (answers, ins, target, prev, judge) in cases.items():
        sols = [solution(f"Add numbers variant {i}.", a, a) if a is not None else
                f"<subtask><description>Add numbers variant {i}.</description></subtask> no tags"
                for i, a in enumerate(answers)]
        rules = [
            ("grain of salt, they might be wrong or incomplete. Try to spot", ins),
            ("You are given the following math problem and two solutions", judge or ""),
            ("consolidate these", "no block"),
            ("For the following math problem", seq(sols)),
        ]
        agent, llm, _ = build(rules, {"Add numbers": unit(1.0)})
        random.seed(0)
        res = agent.run_iteration("Compute 2+3.", None, target,
                                  prev_best_score=1.0 if prev else 0, prev_best_solution=prev)
        out[name] = {"answers": answers, "result": res, "lib": lib(agent),
                     "calls": [c["matched"] for c in llm.calls]}
    # с эталоном в ветке gold: инсайт только при best<1, без штрафа
    for name, answers in [("gold_best_below_1", ["6", "7", "8"]), ("gold_best_1", ["5", "6", "6"])]:
        sols = [solution(f"Add numbers variant {i}.", a, a) for i, a in enumerate(answers)]
        rules = [
            ("grain of salt, they might be wrong or incomplete. Try to spot", f"<insight>{ok}</insight>"),
            ("For the following math problem", seq(sols)),
        ]
        agent, llm, _ = build(rules, {"Add numbers": unit(1.0)}, eval_function=eval_function_gold)
        random.seed(0)
        res = agent.run_iteration("Compute 2+3.", "5", "5")
        out[name] = {"answers": answers, "result": res, "lib": lib(agent),
                     "calls": [c["matched"] for c in llm.calls]}
    return out


def capture_memory():
    data = {
        "compute_IG": ig_cases(),
        "update_future_IG": future_ig_cases(),
        "sample_from_library": sample_cases(),
        "add_new_insight": insight_cases(),
        "add_new_skills": skill_cases(),
        "run_iteration_majority_and_penalty": majority_cases(),
    }
    head = header({
        "compute_IG": EvoLibAgent.compute_IG,
        "update_future_IG_for_insights": EvoLibAgent.update_future_IG_for_insights,
        "update_future_IG_for_skills": EvoLibAgent.update_future_IG_for_skills,
        "_sample_from_library": EvoLibAgent._sample_from_library,
        "add_new_insight": EvoLibAgent.add_new_insight,
        "add_new_skills": EvoLibAgent.add_new_skills,
        "run_iteration": EvoLibAgent.run_iteration,
        "eval_function": "bridge/capture_evolib.py:eval_function (наш чекер вместо matharena)",
    })
    fake.write(METHOD, "memory", head, data)


# --- 4. цикл -------------------------------------------------------------------------------------

PROBLEMS = [
    ("Compute 12+30.", "42", [
        solution("Add two-digit numbers 12 and 30.", "42", "42"),
        solution("Add two-digit numbers 12 and 30.", "42", "$42$"),
        solution("Add two-digit numbers 12 and 30.", "41", "41")]),
    ("Compute 15+27.", "42", [
        solution("Add two-digit numbers 15 and 27 with carry.", "42", "42"),
        solution("Add two-digit numbers 15 and 27 with carry.", "32", "32"),
        solution("Add two-digit numbers 15 and 27 with carry.", "32", "32")]),
    ("Compute 6*7.", "42", [
        solution("Multiply single digits 6 and 7.", "42", "42"),
        solution("Multiply single digits 6 and 7.", "42", "42"),
        solution("Multiply single digits 6 and 7.", "42", "42")]),
    ("Compute 84/2.", "42", [
        solution("Divide 84 by 2.", "42", "42"),
        solution("Divide 84 by 2.", "41", "41"),
        solution("Divide 84 by 2.", "43", "43")]),
]

LOOP_TABLE = [
    ("Add two-digit numbers 12", unit(1.0)),
    ("Add two-digit numbers 15", unit(0.9)),     # похож на первый — слияние навыков
    ("Add two-digit numbers", unit(0.95)),       # итог слияния
    ("Multiply single digits", [0.0, 1.0, 0.0]),
    ("Divide", [0.0, 0.0, 1.0]),
    ("adding two-digit numbers", [0.6, 0.8, 0.0]),
    ("carrying", [0.6, 0.64, 0.48]),              # косинус к первому 0.84 > 0.8 — слияние инсайтов
    ("dividing", [0.0, 0.6, 0.8]),
]


def loop_rules():
    rules = [
        (lambda t: "Try to spot the mistakes" in t and "12+30" in t,
         "<mistake>m</mistake>\n<insight>\nIf adding two-digit numbers, then do add tens and units separately.\n</insight>"),
        (lambda t: "Try to spot the mistakes" in t and "15+27" in t,
         "```insight\nIf carrying a digit, then do not forget to add it to the next place.\n```"),
        (lambda t: "Try to spot the mistakes" in t and "6*7" in t, "<insight>\nN/A\n</insight>"),
        (lambda t: "Try to spot the mistakes" in t and "84/2" in t,
         "<insight>If dividing by 2, then do halve each digit.</insight>"),
        ("consolidate these insights",
         "```insights\nIf adding two-digit numbers or carrying, then do add tens and units and keep the carry.\n```"),
        ("consolidate these example problems",
         solution("Add two-digit numbers a and b.", "a+b", "a+b")),
        ("You are given the following math problem and two solutions", "```judgment\nSolution 1 is better.\n```"),
    ]
    for problem, _, sols in PROBLEMS:
        rules.append((f"Problem: {problem}\n", seq(sols)))
    return rules


def run_loop(gold):
    random.seed(0)
    np.random.seed(0)
    agent, llm, client = build(loop_rules(), LOOP_TABLE, reasoning=True, model="o4-mini",
                               eval_function=eval_function_gold if gold else eval_function,
                               k_q_per_problem=3)
    best_scores = [[0, 0] for _ in PROBLEMS]
    best_solutions = ["" for _ in PROBLEMS]
    iters = []
    # как main() в eval_main.py:643-662, два прохода по вопросам
    for kiter in range(2 * len(PROBLEMS)):
        i = kiter % len(PROBLEMS)
        problem, answer, _ = PROBLEMS[i]
        n0 = len(llm.calls)
        res = agent.run_iteration(problem, answer if gold else None, answer,
                                  prev_best_score=best_scores[i][0], prev_best_solution=best_solutions[i])
        if res is not None and res["is_improving"]:
            best_scores[i][0] = res["best_score"]
            best_scores[i][1] = 1 if res["eval_score"] == 1 else 0
            best_solutions[i] = res["best_solution"]
        iters.append({"kiter": kiter, "problem": i, "result": res,
                      "best_scores": [list(s) for s in best_scores],
                      "calls": llm.calls[n0:], "lib": copy.deepcopy({
                          "skills": {k: v[:3] for k, v in agent.skill_lib.items()},
                          "insights": {k: v[0] for k, v in agent.insight_lib.items()}})})
    return {"iterations": iters, "final_lib": lib(agent),
            "token_usage": agent.llm.get_token_usage(),
            "embedding_calls": client.embed_calls}


def capture_loop():
    data = {
        "setup": {"k_q_per_problem": 3, "threshold": 0.8, "model": "o4-mini", "use_reasoning_api": True,
                  "problems": [(p, a) for p, a, _ in PROBLEMS], "passes": 2, "seed": 0},
        "nogold": run_loop(False),
        "gold": run_loop(True),
    }
    head = header({
        "EvoLibAgent.run_iteration": EvoLibAgent.run_iteration,
        "eval_main.main": em.main,
        "LLMAgent.generate": LLMAgent.generate,
        "EmbeddingModel.embed_strings": EmbeddingModel.embed_strings,
    })
    fake.write(METHOD, "loop", head, data)


if __name__ == "__main__":
    capture_prompts()
    capture_parsers()
    capture_memory()
    capture_loop()
