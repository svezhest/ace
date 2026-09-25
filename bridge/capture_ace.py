"""Эталоны ACE (ace-agent/ace @ 82709de): промпты, разборщики, операции над плейбуком, цикл online, чекеры finance.

запуск из корня стенда: $UPSTREAMS/.venvs/ace/bin/python bridge/capture_ace.py
"""
import contextlib
import importlib.util
import io
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fake  # noqa: E402

REPO = os.path.join(fake.UPSTREAMS, "ace")
sys.path.insert(0, REPO)
TMP = fake.offline()

from ace import ACE  # noqa: E402
from ace.core import Curator, Generator, Reflector  # noqa: E402
from ace.prompts import curator as curator_prompts  # noqa: E402
from ace.prompts import generator as generator_prompts  # noqa: E402
from ace.prompts import reflector as reflector_prompts  # noqa: E402
import playbook_utils as pu  # noqa: E402
import utils  # noqa: E402

spec = importlib.util.spec_from_file_location("finance_dp", os.path.join(REPO, "eval/finance/data_processor.py"))
dp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dp)

METHOD = "ace"
LOG = os.path.join(TMP, "logs")
os.makedirs(LOG, exist_ok=True)


def head_of(funcs):
    # команда задаётся явно: argv[0] относителен, а cwd уже tmp
    return fake.header("ace", funcs)


def quiet(fn, *a, **k):
    """Апстрим много печатает — глушим, чтобы вывод скрипта был коротким."""
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*a, **k)


def scrub(x):
    """Убирает tmp-пути из данных эталона."""
    if isinstance(x, str):
        return x.replace(TMP, "<tmp>")
    if isinstance(x, dict):
        return {k: scrub(v) for k, v in x.items()}
    if isinstance(x, list):
        return [scrub(v) for v in x]
    return x


EMPTY = ACE._initialize_empty_playbook(None)

PLAYBOOK = """## STRATEGIES & INSIGHTS
[sai-00001] helpful=2 harmful=0 :: Read the units before computing.

## FORMULAS & CALCULATIONS
[calc-00002] helpful=0 harmful=1 :: Operating margin = operating income / revenue * 100.

## PROBLEM-SOLVING HEURISTICS
[ph-00003] helpful=0 harmful=0 :: Check the sign of every growth rate.

## OTHERS"""


# --- фейковая модель: ответ по роли (маркер начала промпта) и по задаче (маркер в вопросе) ----------

GEN = "You are an analysis expert"
REF = "You are an expert analyst and educator"
CUR = "You are a master curator of knowledge"

ANSWERS = {  # задача -> (ответ до рефлексии, после)
    "Alpha": ("15.00", "15.00"),
    "Beta": ("$40.00", "40.00"),
    "Gamma": ("3.0", "3.0"),
    "Delta": ("1,200.00", "1,200.00"),
}


def section(text, name, nxt):
    m = re.search(re.escape(f"**{name}:**") + r"\n(.*?)\n\n" + re.escape(f"**{nxt}:**"), text, re.S)
    return m.group(1) if m else ""


def ids_in(text):
    return re.findall(r"\[([^\]\s]+)\] helpful=", text)


def generator_reply(text):
    question = section(text, "Question", "Context")
    task = next((t for t in ANSWERS if t in question), None)
    reflected = section(text, "Reflection", "Question").strip() != "(empty)"
    ids = ids_in(section(text, "Playbook", "Reflection"))
    answer = ANSWERS[task][reflected] if task else "0"
    cited = " ".join(f"[{i}]" for i in ids)
    return json.dumps({
        "reasoning": f"Task {task}. Used bullets {cited}. Reflected: {reflected}.",
        "bullet_ids": ids,
        "final_answer": answer,
    })


def reflector_reply(text):
    used = ids_in(text.split("**Part of Playbook that's used by the generator to answer the question:**")[-1])
    ok = "Predicted answer matches ground truth" in text
    task = next((t for t in ANSWERS if t in text), "?")
    return json.dumps({
        "reasoning": f"Reflection on {task}.",
        "error_identification": "none" if ok else "wrong number format",
        "root_cause_analysis": "n/a",
        "correct_approach": "Output a plain number.",
        "key_insight": f"Insight for {task}: answers are plain floats without currency signs.",
        "bullet_tags": [{"id": i, "tag": "helpful" if ok else "harmful"} for i in used],
    })


CURATOR_BY_STEP = {
    1: json.dumps({"reasoning": "step 1", "operations": [
        {"type": "ADD", "section": "formulas_and_calculations", "content": "Margin = income / revenue * 100."}]}),
    2: json.dumps({"reasoning": "step 2", "operations": [
        {"type": "ADD", "section": "PROBLEM-SOLVING HEURISTICS", "content": "Strip currency signs from answers."},
        {"type": "ADD", "section": "unknown section", "content": "Goes to OTHERS."}]}),
    3: "Here are the ops:\n```json\n" + json.dumps({"reasoning": "step 3", "operations": [
        {"type": "UPDATE", "bullet_id": "calc-00001", "content": "ignored update"},
        {"type": "ADD", "section": "STRATEGIES & INSIGHTS", "content": "Round to two decimals."}]}) + "\n```",
    4: "not a json at all",
}


def curator_reply(text):
    m = re.search(r"Training progress: Sample (\d+) out of", text)
    return CURATOR_BY_STEP.get(int(m.group(1)) if m else 0, json.dumps({"reasoning": "none", "operations": []}))


def make_llm():
    return fake.FakeLLM([(GEN, generator_reply), (REF, reflector_reply), (CUR, curator_reply)])


# --- 1. промпты --------------------------------------------------------------------------------------

def capture_prompts():
    out = {"templates": {
        "GENERATOR_PROMPT": generator_prompts.GENERATOR_PROMPT,
        "REFLECTOR_PROMPT": reflector_prompts.REFLECTOR_PROMPT,
        "REFLECTOR_PROMPT_NO_GT": reflector_prompts.REFLECTOR_PROMPT_NO_GT,
        "CURATOR_PROMPT": curator_prompts.CURATOR_PROMPT,
        "CURATOR_PROMPT_NO_GT": curator_prompts.CURATOR_PROMPT_NO_GT,
        "CURATOR_OPERATIONS_AGGREGATION_PROMPT": curator_prompts.CURATOR_OPERATIONS_AGGREGATION_PROMPT,
    }, "empty_playbook": EMPTY, "filled": {}}

    q = "What is the operating margin of Alpha with revenue $300,000 and operating income $45,000?"
    for provider in ("sambanova", "openai"):
        for json_mode in (False, True):
            llm = make_llm()
            c = llm.client()
            g, r, cu = Generator(c, provider, "gen-m", 4096), Reflector(c, provider, "ref-m", 4096), \
                Curator(c, provider, "cur-m", 4096)
            res = {}
            res["generator"] = quiet(g.generate, question=q, playbook=PLAYBOOK, context="ctx text",
                                     reflection="(empty)", use_json_mode=json_mode, log_dir=LOG)[:2]
            res["generator_reflected"] = quiet(g.generate, question=q, playbook=PLAYBOOK, context="",
                                               reflection="Previous answer used a $ sign.",
                                               use_json_mode=json_mode, log_dir=LOG)[:2]
            used = pu.extract_playbook_bullets(PLAYBOOK, ["calc-00002", "ph-00003"])
            res["reflector_gt"] = quiet(r.reflect, question=q, reasoning_trace="trace", predicted_answer="$15.00",
                                        ground_truth="15.0", environment_feedback="Predicted answer does not match ground truth",
                                        bullets_used=used, use_ground_truth=True, use_json_mode=json_mode, log_dir=LOG)[:2]
            res["reflector_nogt"] = quiet(r.reflect, question=q, reasoning_trace="trace", predicted_answer="15.00",
                                          ground_truth=None, environment_feedback="Predicted answer matches ground truth",
                                          bullets_used="(No bullets used by generator)", use_ground_truth=False,
                                          use_json_mode=json_mode, log_dir=LOG)[:2]
            stats = pu.get_playbook_stats(PLAYBOOK)
            for gt in (True, False):
                res["curator_gt" if gt else "curator_nogt"] = quiet(
                    cu.curate, current_playbook=PLAYBOOK, recent_reflection="Use plain numbers.",
                    question_context="ctx text", current_step=1, total_samples=4, token_budget=80000,
                    playbook_stats=stats, use_ground_truth=gt, use_json_mode=json_mode, call_id="c",
                    log_dir=LOG, next_global_id=4)[:3]
            out["filled"][f"{provider}_json{int(json_mode)}"] = {"results": res, "calls": llm.calls}

    head = head_of({
        "Generator.generate": Generator.generate, "Reflector.reflect": Reflector.reflect,
        "Curator.curate": Curator.curate, "timed_llm_call": sys.modules["llm"].timed_llm_call,
        "GENERATOR_PROMPT": "ace/prompts/generator.py:6", "REFLECTOR_PROMPT": "ace/prompts/reflector.py:6",
        "REFLECTOR_PROMPT_NO_GT": "ace/prompts/reflector.py:63", "CURATOR_PROMPT": "ace/prompts/curator.py:6",
        "CURATOR_PROMPT_NO_GT": "ace/prompts/curator.py:69",
    })
    fake.write(METHOD, "prompts", head, scrub(out))


# --- 2. разборщики -----------------------------------------------------------------------------------

BULLET_TEXTS = [
    'Used [calc-00001] and [fin-00002].',
    'Used [ph-00003] and [sai-00004].',                       # слаг из двух букв
    '{"bullet_ids": ["calc-00001", "ph-00003"], "final_answer": "1"}',
    '{"bullet_ids": "[\\"ph-00001\\"]", "final_answer": "1"}',  # список строкой
    '{"bullet_ids": ["calc-1"], "final_answer": "1"}',
    'Used [CALC-00001] and [Calc-00002] and [calc-0001] and [calc-000001].',
    'bullet_ids: ["calc-00001", "misc-00007"]',
    '```json\n{"bullet_ids": ["calc-00001"], "final_answer": "1"}\n```',
    'no ids here',
    '[code-00012][err-00013] [ctx-00014]',
]

JSON_TEXTS = [
    '{"a": 1}',
    '  {"a": 1}\n',
    'text before ```json\n{"a": 1}\n``` after',
    '```JSON\n{"a": 2}\n```',
    '```json\n{"a": 1,}\n```\n```json\n{"b": 2}\n```',
    '{"a": 1} and then {"b": 2}',
    'broken {"a": 1 and more',
    'nested {"a": {"b": [1, 2, {"c": "}"}]}} tail',
    '{"a": "brace } in string"}',
    '[1, 2, 3]',
    '```\n{"a": 1}\n```',
    "{'a': 1}",
    '',
]

TAG_TEXTS = [
    '{"reasoning": "r", "bullet_tags": [{"id": "calc-00001", "tag": "helpful"}]}',
    'prose then "bullet_tags": [{"id": "ph-00003", "tag": "harmful"}, {"id": "x", "tag": "neutral"}] tail',
    '"bullet_tags": [{"id": "a", "tag": "helpful"}',
    '"bullet_tags": []',
    'no tags',
    '```json\n{"bullet_tags": [{"bullet": "calc-00001", "tag": "helpful"}]}\n```',
]

CURATOR_TEXTS = [
    '{"reasoning": "r", "operations": [{"type": "ADD", "section": "s", "content": "c"}]}',
    '{"reasoning": "r", "operations": []}',
    '{"operations": []}',
    '{"reasoning": "r", "operations": [{"type": "ADD", "section": "s"}]}',
    '{"reasoning": "r", "operations": [{"type": "DELETE", "bullet_id": "calc-00001"}]}',
    '{"reasoning": "r", "operations": [{"type": "FOO"}]}',
    '{"reasoning": "r", "operations": "ADD"}',
    '```json\n{"reasoning": "r", "operations": [{"type": "ADD", "section": "s", "content": "c"}]}\n```',
    'nothing',
]

ANSWER_TEXTS = [
    '{"reasoning": "r", "final_answer": "15.00"}',
    '{"reasoning": "r", "final_answer": 15}',
    '{"reasoning": "r", "final_answer": "$1,200.50"}',
    'Some text "final_answer": "42" more',
    "Some text 'final_answer': '42' more",
    '"final_answer": 3.14}',
    'Finish[7] then Finish[8]',
    'The final answer is: $\\boxed{12.5}$',
    'The final answer is 99.',
    'The final answer is $5$',
    '{"final_answer": "a"} {"final_answer": "b"}',
    '["x"]',
    'nothing',
]


def capture_parsers():
    g = Generator(None, "sambanova", "m")
    r = Reflector(None, "sambanova", "m")
    cu = Curator(None, "sambanova", "m")
    out = {
        "_extract_bullet_ids_regex": [{"in": t, "out": fake.call(g._extract_bullet_ids_regex, t)} for t in BULLET_TEXTS],
        "_extract_bullet_ids": [{"in": t, "json_mode": jm, "out": quiet(fake.call, g._extract_bullet_ids, t, jm)}
                                for t in BULLET_TEXTS for jm in (False, True)],
        "_extract_bullet_tags": [{"in": t, "json_mode": jm, "out": quiet(fake.call, r._extract_bullet_tags, t, jm)}
                                 for t in TAG_TEXTS for jm in (False, True)],
        "extract_json_from_text": [{"in": t, "out": quiet(fake.call, pu.extract_json_from_text, t)} for t in JSON_TEXTS],
        "_extract_and_validate_operations": [{"in": t, "out": quiet(fake.call, cu._extract_and_validate_operations, t)}
                                             for t in CURATOR_TEXTS],
        "extract_answer": [{"in": t, "out": fake.call(utils.extract_answer, t)} for t in ANSWER_TEXTS],
    }
    head = head_of({
        "Generator._extract_bullet_ids": Generator._extract_bullet_ids,
        "Generator._extract_bullet_ids_regex": Generator._extract_bullet_ids_regex,
        "Reflector._extract_bullet_tags": Reflector._extract_bullet_tags,
        "extract_json_from_text": pu.extract_json_from_text,
        "Curator._extract_and_validate_operations": Curator._extract_and_validate_operations,
        "extract_answer": utils.extract_answer,
    })
    fake.write(METHOD, "parsers", head, out)


# --- 3. память ---------------------------------------------------------------------------------------

LINES = [
    "[calc-00001] helpful=3 harmful=1 :: Use the formula.",
    "  [ph-00002] helpful=0 harmful=0 ::   spaced content  ",
    "[calc-00003] helpful=1 harmful=0 :: a :: b",
    "[x] helpful=1 harmful=2 :: short id",
    "[calc-00004] helpful=-1 harmful=0 :: negative",
    "[calc-00005] helpful=1 harmful=0 no separator",
    "- plain bullet",
    "## FORMULAS & CALCULATIONS",
]

SECTIONS = [
    "STRATEGIES & INSIGHTS", "FORMULAS & CALCULATIONS", "CODE SNIPPETS & TEMPLATES", "COMMON MISTAKES TO AVOID",
    "PROBLEM-SOLVING HEURISTICS", "problem_solving_heuristics", "CONTEXT CLUES & INDICATORS", "OTHERS",
    "others", "meta_strategies", "financial_strategies_and_insights", "strategies_and_insights",
    "formulas_and_calculations", "Problem Heuristics", "general", "a", "one two three four five six",
    "  Mixed Case  ",
]

OPS = {
    "add_existing_snake": [{"type": "ADD", "section": "formulas_and_calculations", "content": "A"}],
    "add_existing_header_case": [{"type": "ADD", "section": "FORMULAS & CALCULATIONS", "content": "B"}],
    "add_hyphen_header": [{"type": "ADD", "section": "PROBLEM-SOLVING HEURISTICS", "content": "C"}],
    "add_hyphen_snake": [{"type": "ADD", "section": "problem_solving_heuristics", "content": "D"}],
    "add_missing": [{"type": "ADD", "section": "no such section", "content": "E"}],
    "add_general": [{"type": "ADD", "section": "general", "content": "F"}],
    "add_no_section": [{"type": "ADD", "content": "G"}],
    "add_others": [{"type": "ADD", "section": "OTHERS", "content": "H"}],
    "update_delete_merge": [
        {"type": "UPDATE", "bullet_id": "calc-00002", "content": "changed"},
        {"type": "DELETE", "bullet_id": "sai-00001"},
        {"type": "MERGE", "source_ids": ["sai-00001", "calc-00002"], "content": "merged"},
    ],
    "unknown_type": [{"type": "FOO", "section": "OTHERS", "content": "I"}],
    "several": [
        {"type": "ADD", "section": "strategies_and_insights", "content": "J"},
        {"type": "ADD", "section": "formulas_and_calculations", "content": "K"},
        {"type": "ADD", "section": "strategies_and_insights", "content": "L"},
    ],
}

TAGS = {
    "helpful_harmful_neutral": [{"id": "sai-00001", "tag": "helpful"}, {"id": "calc-00002", "tag": "harmful"},
                                {"id": "ph-00003", "tag": "neutral"}],
    "bullet_key": [{"bullet": "calc-00002", "tag": "helpful"}],
    "unknown_id_and_tag": [{"id": "zzz-00009", "tag": "helpful"}, {"id": "sai-00001", "tag": "useful"}],
    "duplicate_id_last_wins": [{"id": "sai-00001", "tag": "helpful"}, {"id": "sai-00001", "tag": "harmful"}],
    "empty": [],
    "strings": ["sai-00001"],
}


def capture_memory():
    no_others = PLAYBOOK.replace("\n\n## OTHERS", "")
    ops = {}
    for name, o in OPS.items():
        for pname, pb in (("playbook", PLAYBOOK), ("empty", EMPTY), ("no_others", no_others)):
            ops[f"{name}/{pname}"] = quiet(fake.call, pu.apply_curator_operations, pb, o, 4)
    out = {
        "parse_playbook_line": [{"in": s, "out": fake.call(pu.parse_playbook_line, s)} for s in LINES],
        "get_section_slug": [{"in": s, "out": fake.call(utils.get_section_slug, s)} for s in SECTIONS],
        "get_next_global_id": [{"in": p, "out": fake.call(pu.get_next_global_id, p)}
                               for p in (PLAYBOOK, EMPTY, "[a-7] helpful=0 harmful=0 :: x\n[b-00003] helpful=0 harmful=0 :: y",
                                         "[abc] helpful=0 harmful=0 :: no number")],
        "update_bullet_counts": {k: quiet(fake.call, pu.update_bullet_counts, PLAYBOOK, v) for k, v in TAGS.items()},
        "apply_curator_operations": ops,
        "extract_playbook_bullets": [{"ids": ids, "out": fake.call(pu.extract_playbook_bullets, PLAYBOOK, ids)}
                                     for ids in (["calc-00002", "ph-00003"], [], ["nope-00001"])],
        "get_playbook_stats": fake.call(pu.get_playbook_stats, PLAYBOOK),
        "format_playbook_line": fake.call(pu.format_playbook_line, "calc-00001", 0, 0, "text"),
    }
    head = head_of({
        "parse_playbook_line": pu.parse_playbook_line, "get_section_slug": utils.get_section_slug,
        "get_next_global_id": pu.get_next_global_id, "update_bullet_counts": pu.update_bullet_counts,
        "apply_curator_operations": pu.apply_curator_operations,
        "extract_playbook_bullets": pu.extract_playbook_bullets, "get_playbook_stats": pu.get_playbook_stats,
    })
    fake.write(METHOD, "memory", head, out)


# --- 4. цикл online ----------------------------------------------------------------------------------

def formula_item(name, question, target):
    return {"context": "Use formula X to answer the question. Answer with a numerical answer with 2 decimal places. "
                       f"Question:  \"{name}: {question}\". Answer:", "target": target}


RAW = [
    formula_item("Alpha", "revenue $300,000, operating income $45,000; find the operating margin.", "15.0"),
    formula_item("Beta", "next dividend $4, growth 3%, required return 13%; price by DDM.", "40.0"),
    formula_item("Gamma", "dividends $1 per share, price $40; find the dividend yield in percent.", "2.5"),
    formula_item("Delta", "revenue $1,500 and cost $300; find the gross profit.", "1200.0"),
]


def run_online(no_ground_truth):
    llm = make_llm()
    ace = quiet(ACE, api_provider="sambanova", generator_model="gen-m", reflector_model="ref-m",
                curator_model="cur-m", max_tokens=4096)
    for agent in (ace.generator, ace.reflector, ace.curator):
        agent.api_client = llm.client()
    proc = dp.DataProcessor("formula")
    samples = quiet(proc.process_task_data, RAW)
    config = {"task_name": "formula", "json_mode": False, "no_ground_truth": no_ground_truth,
              "save_dir": os.path.join(TMP, "results"), "test_workers": 1, "online_eval_frequency": 2,
              "num_epochs": 1, "max_num_rounds": 3, "curator_frequency": 1, "save_steps": 50,
              "playbook_token_budget": 80000}
    results = quiet(ace.run, mode="online", test_samples=samples, data_processor=proc, config=config)
    return {"config": config, "samples": samples, "results": results, "final_playbook": ace.playbook,
            "next_global_id": ace.next_global_id, "calls": llm.calls}


def capture_loop():
    out = {"online_gt": run_online(False), "online_nogt": run_online(True)}
    head = head_of({
        "ACE.run": ACE.run, "ACE._online_train_and_test": ACE._online_train_and_test,
        "ACE._train_single_sample": ACE._train_single_sample, "evaluate_test_set": utils.evaluate_test_set,
        "DataProcessor.process_task_data": dp.DataProcessor.process_task_data,
    })
    fake.write(METHOD, "loop", head, scrub(out))


# --- 5. чекеры finance -------------------------------------------------------------------------------

FORMULA_CASES = [
    ("15.00", "15.0"), ("15", "15.0"), ("$15.00", "15.0"), ("15.0", "$15.0"), ("$15.0", "$15.0"),
    ("1,200.00", "1200.0"), ("1200", "1,200.0"), ("15%", "15.0"), ("15.004", "15.0"), ("1.5e1", "15.0"),
    (" 15.0 ", "15.0"), ("No final answer found", "15.0"), ("abc", "abc"), ("-3.5", "-3.50"),
    ("5 million", "5000000.0"), ("5000000.0", "5000000.0"), ("nan", "nan"), ("inf", "inf"),
]

FINER_CASES = [
    ("Revenues,InterestExpense", "Revenues,InterestExpense"),
    ("revenues , interestexpense", "Revenues,InterestExpense"),
    ("Revenues", "Revenues,InterestExpense"),
    ("Revenues,InterestExpense,Goodwill", "Revenues,InterestExpense"),
    ("$1,200", "1200"),
    ("1200.0", "1200"),
    ("1+1", "2"),
    ("2", "1+1"),
    ("$5", "5"),
    ("5%", "5"),
    ("0.5", "1/2"),
    ("True", "1"),
    ("", ""),
    ("Goodwill,", "Goodwill"),
]


def capture_eval():
    formula = dp.DataProcessor("formula")
    finer = dp.DataProcessor("finer")
    out = {
        "formula_answer_is_correct": [{"pred": p, "target": t, "out": fake.call(formula.answer_is_correct, p, t)}
                                      for p, t in FORMULA_CASES],
        "finer_answer_is_correct": [{"pred": p, "target": t, "out": fake.call(finer.answer_is_correct, p, t)}
                                    for p, t in FINER_CASES],
        "finer_counts": [{"pred": p, "target": t, "out": fake.call(finer._finer_answer_is_correct, p, t, True)}
                         for p, t in FINER_CASES],
        "finer_evaluate_accuracy": fake.call(finer.evaluate_accuracy, [p for p, _ in FINER_CASES],
                                             [t for _, t in FINER_CASES]),
        "formula_evaluate_accuracy": fake.call(formula.evaluate_accuracy, [p for p, _ in FORMULA_CASES],
                                               [t for _, t in FORMULA_CASES]),
        "parse_context_and_question_formula": fake.call(dp.parse_context_and_question_formula, RAW[0]["context"]),
        "parse_instruction_and_input": fake.call(
            dp.parse_instruction_and_input,
            "Instruction: Tag the numbers.\nInput: Revenue was $5 million.\nAnswer: "),
    }
    head = head_of({
        "DataProcessor.answer_is_correct": dp.DataProcessor.answer_is_correct,
        "DataProcessor._formula_answer_is_correct": dp.DataProcessor._formula_answer_is_correct,
        "DataProcessor._finer_answer_is_correct": dp.DataProcessor._finer_answer_is_correct,
        "DataProcessor.evaluate_accuracy": dp.DataProcessor.evaluate_accuracy,
        "parse_context_and_question_formula": dp.parse_context_and_question_formula,
        "parse_instruction_and_input": dp.parse_instruction_and_input,
    })
    fake.write(METHOD, "eval", head, out)


if __name__ == "__main__":
    capture_prompts()
    capture_parsers()
    capture_memory()
    capture_loop()
    capture_eval()
