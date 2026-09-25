"""Эталоны Dynamic Cheatsheet (dynamic-cheatsheet 5cfe3c3) на фейковой модели.

Подмена: LanguageModel.client.openai_client -> fake.FakeOpenAI, весь путь UnifiedLLMClient
(параметры запроса, ретраи) остаётся апстримным. Исполнение кода не срабатывает: в ответах фейка
нет "EXECUTE CODE!".

    .venvs/light/bin/python bridge/capture_dc.py      (из корня ace-bridge)

Пишет fixtures/dc/: prompts, parsers, evals, memory, loop и cheatsheet_compare
(HEAD против пропатченного repro и нашего ace/parse.py).
"""
import copy
import hashlib
import importlib.util
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fake  # noqa: E402

# до импорта апстрима: language_model.py при импорте зовёт load_dotenv("config.env") относительно cwd
fake.offline()

REPO = "dynamic-cheatsheet"
ROOT = os.path.join(fake.UPSTREAMS, REPO)
sys.path.insert(0, ROOT)

import numpy as np  # noqa: E402
from dynamic_cheatsheet.language_model import LanguageModel  # noqa: E402
from dynamic_cheatsheet.utils import evaluation, extractor  # noqa: E402

PATCHED = "/Users/user/Projects/itmo/cs-masters/thesis/repro/dynamic-cheatsheet/dynamic_cheatsheet/utils/extractor.py"
OURS = "/Users/user/Projects/ace/ace/parse.py"

# настройки run_benchmark.py по умолчанию
MODEL = "openai/gpt-4o-mini"
TEMPERATURE = 0.0
MAX_TOKENS = 2048


def read(name):
    with open(os.path.join(ROOT, "prompts", name), encoding="utf-8") as f:
        return f.read()


GENERATOR = read("generator_prompt.txt")
CURATOR = read("curator_prompt_for_dc_cumulative.txt")
SYNTH = read("curator_prompt_for_dc_retrieval_synthesis.txt")

# --- фейковая модель ---------------------------------------------------------------------------

SHEET_LONG = """Version: {v}

SOLUTIONS, IMPLEMENTATION PATTERNS, AND CODE SNIPPETS
<memory_item>
<description>
Equation balancing: try multiplication and division first, then fix the remainder with + and -.
</description>
<example>
14 ? 16 ? 20 ? 15 ? 23 = 25 -> 14 - 16 / 20 * 15 + 23 = 25
</example>
</memory_item>
** Count: {v}

GENERAL META-REASONING STRATEGIES
<memory_item>
<description>
For multiple-choice physics, estimate orders of magnitude before computing (question #{q}).
</description>
</memory_item>
** Count: 1"""

TEMPLATE_ECHO = """Version: [Version Number]

SOLUTIONS, IMPLEMENTATION PATTERNS, AND CODE SNIPPETS
<memory_item>
[...]
</memory_item>"""


def qnum(text):
    """Номер текущего вопроса: последнее вхождение "Question #k" (шаблоны ставят вопрос в конец)."""
    found = re.findall(r"Question #(\d+)", text)
    return int(found[-1]) if found else 0


GEN_ANSWERS = {
    1: "Resolve by energy-time uncertainty.\nFINAL ANSWER:\n<answer>\n(C)\n</answer>",
    2: "Try * and / first.\nFINAL ANSWER:\n<answer>\n14 - 16 / 20 * 15 + 23 = 25\n</answer>",
    3: "Balance with + only.\nFINAL ANSWER:\n<answer>\n1 + 2 + 3 = 6\n</answer>",
    4: "Estimate first.\nFINAL ANSWER:\n<answer>\nB\n</answer>",
    5: "No tags here, answer is (D).",
}


def generator_reply(text):
    return GEN_ANSWERS.get(qnum(text), "FINAL ANSWER:\n<answer>\n0\n</answer>")


def curator_reply(text):
    q = qnum(text)
    if q == 2:
        return "The previous cheatsheet is fine, nothing to add."  # нет блока: остаётся старый
    if q == 3:
        return f"NEW CHEATSHEET:\n```\n<cheatsheet>\nVersion: 3\nshort sheet q{q}\n</cheatsheet>\n```"
    if q == 4:
        return f"<cheatsheet>\n{TEMPLATE_ECHO}\n</cheatsheet>"
    return f"NEW CHEATSHEET:\n```\n<cheatsheet>\n{SHEET_LONG.format(v=q, q=q)}\n</cheatsheet>\n```"


def synth_reply(text):
    q = qnum(text)
    if q == 3:
        return "I could not synthesize anything useful."  # без блока решатель получает сами пары
    return f"<cheatsheet>\nSynthesized for question #{q}.\n{SHEET_LONG.format(v=q, q=q)}\n</cheatsheet>"


def new_llm():
    return fake.FakeLLM(rules=[
        ("# CHEATSHEET REFRENCE CURATOR", curator_reply),
        ("# CHEATSHEET CURATOR\n", synth_reply),
        ("# GENERATOR (PROBLEM SOLVER)", generator_reply),
    ], default="(unmatched)")


def new_model(llm):
    model = LanguageModel(model_name=MODEL)
    # апстрим дописывает в history при исполнении кода — пишем копию запроса
    model.client.openai_client = fake.FakeOpenAI(lambda m, **kw: llm(copy.deepcopy(m), **kw))
    return model


# --- входы как в run_benchmark.py --------------------------------------------------------------

GPQA_1 = ("Two quantum states with energies E1 and E2 have a lifetime of 10^-9 sec and 10^-8 sec, "
          "respectively. Which energy difference lets them be clearly resolved?\n"
          "Options:\n(A) 10^-9 eV\n(B) 10^-8 eV\n(C) 10^-4 eV\n(D) 10^-11 eV")
MEB_1 = "14 ? 16 ? 20 ? 15 ? 23 = 25"
MEB_2 = "1 ? 2 ? 3 = 6"
GPQA_2 = "Which particle is a lepton?\nOptions:\n(A) proton\n(B) muon\n(C) neutron\n(D) pion"
GPQA_3 = "Which is a noble gas?\nOptions:\n(A) N\n(B) O\n(C) H\n(D) Ne"
RAW = [GPQA_1, MEB_1, MEB_2, GPQA_2, GPQA_3]
TASKS = ["GPQA_Diamond", "MathEquationBalancer", "MathEquationBalancer", "GPQA_Diamond", "GPQA_Diamond"]
MEB_PREFIX = ("Below is an equation with missing operators. Your task is to fill in the blanks with the correct "
              "mathematical operators: +, -, *, or /. Ensure that the equation is correct once the operators are "
              "added. The operators should be placed in the sequence they appear from left to right. Include the "
              "full equation with the operators filled in. For instance, for the equation 1 ? 2 ? 3 = 6, the "
              "correct answer is 1 + 2 + 3 = 6.\n\nEquation: ")


def current_input(idx):
    text = f"Question #{idx + 1}:\n{RAW[idx]}"
    return MEB_PREFIX + text if TASKS[idx] == "MathEquationBalancer" else text


# эмбеддинги подобраны без равенств близостей: на 5-м вопросе top-3 из 4 отбрасывает первый
EMBEDDINGS = np.array([
    [1.0, 0.0, 0.0],
    [0.0, 1.0, 0.0],
    [0.9, 0.1, 0.0],
    [0.6, 0.8, 0.0],
    [0.0, 0.2, 1.0],
])


def run(approach, n, max_num_rounds=1, retrieve_top_k=3, cheatsheet_template=None):
    """Цикл run_benchmark.py: шпаргалка и выходы решателя передаются от вопроса к вопросу."""
    llm = new_llm()
    model = new_model(llm)
    cheatsheet = "(empty)"
    outputs, so_far = [], []
    questions = [current_input(i) for i in range(n)]
    for idx in range(n):
        start = len(llm.calls)
        out = model.advanced_generate(
            approach_name=approach,
            input_txt=questions[idx],
            cheatsheet=cheatsheet,
            generator_template=GENERATOR,
            cheatsheet_template=cheatsheet_template or "(empty)",
            temperature=TEMPERATURE,
            max_tokens=MAX_TOKENS,
            max_num_rounds=max_num_rounds,
            allow_code_execution=True,
            code_execution_flag="EXECUTE CODE!",
            # как в run_benchmark: корпус — сырые входы датасета, не отформатированные
            original_input_corpus=RAW[:idx + 1],
            original_input_embeddings=EMBEDDINGS[:idx + 1],
            generator_outputs_so_far=so_far,
            retrieve_top_k=retrieve_top_k,
        )
        so_far.append(out["final_output"])
        cheatsheet = out["final_cheatsheet"]
        outputs.append({"output": out, "calls": llm.calls[start:]})
    return outputs


# --- уровни ------------------------------------------------------------------------------------

def prompts():
    one = run("DynamicCheatsheet_Cumulative", 1, cheatsheet_template=CURATOR)[0]
    rs = run("DynamicCheatsheet_RetrievalSynthesis", 2, cheatsheet_template=SYNTH)
    two_rounds = run("DynamicCheatsheet_Cumulative", 1, max_num_rounds=2, cheatsheet_template=CURATOR)[0]
    return {
        "templates": {"generator_prompt.txt": GENERATOR,
                      "curator_prompt_for_dc_cumulative.txt": CURATOR,
                      "curator_prompt_for_dc_retrieval_synthesis.txt": SYNTH},
        "cumulative": {"input": current_input(0), "cheatsheet": "(empty)",
                       "generator": one["calls"][0], "curator": one["calls"][1]},
        "cumulative_two_rounds": {"input": current_input(0), "calls": two_rounds["calls"]},
        "synthesis_first": {"input": current_input(0), "calls": rs[0]["calls"]},
        "synthesis_with_pairs": {"input": current_input(1), "calls": rs[1]["calls"]},
    }


CHEATSHEET_INPUTS = {
    "normal": "Some analysis.\n<cheatsheet>\nVersion: 2\nkeep this\n</cheatsheet>\ntrailing text",
    "two_blocks": "<cheatsheet>A</cheatsheet> middle <cheatsheet>B</cheatsheet>",
    "two_open_one_close": "<cheatsheet>A\n<cheatsheet>B</cheatsheet>",
    "tag_mentioned_in_prose": "I will write the <cheatsheet> block below.\n<cheatsheet>REAL</cheatsheet>",
    "no_closing": "<cheatsheet>\nVersion: 3\nunterminated",
    "closing_only": "text </cheatsheet>",
    "upper_case": "<CHEATSHEET>X</CHEATSHEET>",
    "mixed_case": "<Cheatsheet>X</Cheatsheet>",
    "empty_block": "<cheatsheet></cheatsheet>",
    "blank_block": "<cheatsheet>\n   \n</cheatsheet>",
    "empty_response": "",
    "no_tag": "No changes needed.",
    "inside_code_fence": "NEW CHEATSHEET:\n```\n<cheatsheet>\nVersion: 2\nfenced\n</cheatsheet>\n```",
    "template_echo": f"<cheatsheet>\n{TEMPLATE_ECHO}\n</cheatsheet>",
    "short_real": "<cheatsheet>\nVersion: 1\nUse * before +.\n</cheatsheet>",
    "long_real": f"<cheatsheet>\n{SHEET_LONG.format(v=5, q=5)}\n</cheatsheet>",
    "leading_whitespace": "\n\n  <cheatsheet>  padded  </cheatsheet>  \n",
}

ANSWER_INPUTS = {
    "answer_tag": "<answer>(A)</answer>",
    "final_answer_block": "FINAL ANSWER:\n<answer>\n42\n</answer>",
    "two_answer_tags": "<answer>1</answer> then reconsider <answer>2</answer>",
    "no_closing": "<answer> 7 and more",
    "upper_case": "<ANSWER>5</ANSWER>",
    "empty_answer": "<answer></answer>",
    "final_answer_backticks": "FINAL ANSWER: ```\n12\n```",
    "final_answer_quotes": "FINAL ANSWER: '''13'''",
    "final_answer_both_fences": "FINAL ANSWER: '''a''' then ```b```",
    "final_answer_plain": "FINAL ANSWER: 14",
    "final_answer_python": "FINAL ANSWER:\n```python\ndef f():\n    return 1\n```",
    "final_answer_lower": "final answer: 15",
    "empty": "",
    "no_marker": "The answer is (B).",
    "equation": "FINAL ANSWER:\n<answer>\n1 + 2 * 3 = 7\n</answer>",
    "answer_in_code_then_final": "```\n<answer>x</answer>\n```\nFINAL ANSWER:\n<answer>\ny\n</answer>",
}


def parsers():
    old = "OLD CHEATSHEET"
    return {
        "extract_cheatsheet": {k: {"input": v, "old": old, **fake.call(extractor.extract_cheatsheet, v, old)}
                               for k, v in CHEATSHEET_INPUTS.items()},
        "extract_answer": {k: {"input": v, **fake.call(extractor.extract_answer, v)}
                           for k, v in ANSWER_INPUTS.items()},
    }


MEB_CASES = [
    ("same", "1 + 2 + 3 = 6", "1 + 2 + 3 = 6"),
    ("other_ops_same_value", "2 * 2 = 4", "2 + 2 = 4"),
    ("no_rhs", "1 + 2 + 3", "1 + 2 + 3 = 6"),
    ("wrong_value", "1 * 2 + 3 = 6", "1 + 2 + 3 = 6"),
    ("other_numbers", "1 + 2 + 4 = 6", "1 + 2 + 3 = 6"),
    ("unicode_times", "2 × 3 = 6", "2 * 3 = 6"),
    ("unicode_div", "8 ÷ 4 = 2", "8 / 4 = 2"),
    ("dataset_example", "14 - 16 / 20 * 15 + 23 = 25", "14 - 16 / 20 * 15 + 23 = 25"),
    ("float_rounding", "1 / 3 * 3 = 1", "1 * 3 / 3 = 1"),
    ("float_target", "7 / 2 = 3.5", "7 / 2 = 3.5"),
    ("no_spaces", "1+2+3=6", "1 + 2 + 3 = 6"),
    ("leading_minus", "-1 + 2 = 1", "-1 + 2 = 1"),
    ("prose", "The answer is 1 + 2 + 3 = 6", "1 + 2 + 3 = 6"),
    ("empty", "", "1 + 2 + 3 = 6"),
    ("zero_division", "1 / 0 = 1", "1 - 0 = 1"),
    ("no_answer_marker", "No final answer found", "1 + 2 + 3 = 6"),
]

MC_INPUT = "Question #1:\nWhich particle is a lepton?\nOptions:\n(A) proton\n(B) muon\n(C) neutron\n(D) pion"
MC_INPUT_DOT = "Which particle is a lepton?\nA. proton\nB. muon\nC. neutron\nD. pion"
MC_CASES = [
    ("exact", MC_INPUT, "(B)", "(B)"),
    ("letter", MC_INPUT, "B", "(B)"),
    ("lower_letter", MC_INPUT, "b", "(B)"),
    ("letter_dot", MC_INPUT, "B.", "(B)"),
    ("option_word", MC_INPUT, "Option B", "(B)"),
    ("answer_is", MC_INPUT, "The answer is B.", "(B)"),
    ("paren_close", MC_INPUT, "B) muon", "(B)"),
    ("option_text", MC_INPUT, "muon", "(B)"),
    ("option_text_in_sentence", MC_INPUT, "It is the muon.", "(B)"),
    ("wrong_letter", MC_INPUT, "(A)", "(B)"),
    ("two_letters", MC_INPUT, "(A) or (B)", "(B)"),
    ("empty", MC_INPUT, "", "(B)"),
    ("target_plain_letter", MC_INPUT, "(B)", "B"),
    ("dot_options", MC_INPUT_DOT, "muon", "(B)"),
    ("no_final_answer", MC_INPUT, "No final answer found", "(B)"),
    ("starts_with_letter_word", MC_INPUT, "Because", "(B)"),
    ("backticks", MC_INPUT, "`(B)`", "(B)"),
]

# run_benchmark для AIME: eval_for_exact_matching_with_no_punctuation(final_answer.lower(), target.lower())
EXACT_CASES = [
    ("same", "42", "42"),
    ("trailing_dot", "42.", "42"),
    ("thousands_comma", "4,200", "4200"),
    ("leading_zero", "042", "42"),
    ("dollar", "$42", "42"),
    ("latex_dollars", "$42$", "42"),
    ("space", " 42", "42"),
    ("newline", "4\n2", "4 2"),
    ("float", "42.0", "42"),
    ("upper", "abc", "ABC"),
]


def evals():
    return {
        "eval_equation_balancer": [{"name": n, "output": o, "target": t, **fake.call(evaluation.eval_equation_balancer, None, o, t)}
                                   for n, o, t in MEB_CASES],
        "eval_for_multiple_choice": [{"name": n, "input": i, "final_answer": a, "target": t,
                                      **fake.call(evaluation.eval_for_multiple_choice, i, a, t)}
                                     for n, i, a, t in MC_CASES],
        "eval_for_exact_matching_with_no_punctuation": [{"name": n, "output": o, "target": t,
                                                         **fake.call(evaluation.eval_for_exact_matching_with_no_punctuation, o, t)}
                                                        for n, o, t in EXACT_CASES],
    }


def memory():
    """Сборка показанного контекста без куратора: отбор top-k и оформление пар (Dynamic_Retrieval),
    все пары подряд (FullHistoryAppending); шпаргалка решателя — из записанного промпта."""
    out = {}
    for approach, k in [("Dynamic_Retrieval", 3), ("Dynamic_Retrieval", 2), ("FullHistoryAppending", 3)]:
        steps = run(approach, 5, retrieve_top_k=k)
        out[f"{approach}_top{k}" if approach == "Dynamic_Retrieval" else approach] = [
            {"top_k_original_inputs": s["output"]["top_k_original_inputs"],
             "shown_cheatsheet": s["output"]["final_cheatsheet"]} for s in steps]
    out["embeddings"] = EMBEDDINGS
    return out


def loop():
    def pack(steps):
        return [{"input": s["output"]["input_txt"],
                 "final_answer": s["output"]["final_answer"],
                 "final_cheatsheet": s["output"]["final_cheatsheet"],
                 "steps": s["output"]["steps"],
                 "top_k_original_inputs": s["output"].get("top_k_original_inputs"),
                 "calls": s["calls"]} for s in steps]
    return {
        "settings": {"model_name": MODEL, "temperature": TEMPERATURE, "max_tokens": MAX_TOKENS,
                     "max_num_rounds": 1, "retrieve_top_k": 3, "embeddings": EMBEDDINGS},
        "DynamicCheatsheet_Cumulative": pack(run("DynamicCheatsheet_Cumulative", 5, cheatsheet_template=CURATOR)),
        "DynamicCheatsheet_RetrievalSynthesis": pack(run("DynamicCheatsheet_RetrievalSynthesis", 5, cheatsheet_template=SYNTH)),
    }


def load_file(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def cheatsheet_compare():
    """HEAD extract_cheatsheet против пропатченного в repro и нашего parse.opened("cheatsheet").
    У нас None значит «оставить старый» — приводим к old для сравнения."""
    patched = load_file(PATCHED, "dc_patched_extractor").extract_cheatsheet
    ours = load_file(OURS, "ace_parse").opened("cheatsheet")
    old = "OLD CHEATSHEET"
    rows = {}
    for k, v in CHEATSHEET_INPUTS.items():
        head = fake.call(extractor.extract_cheatsheet, v, old)
        pat = fake.call(patched, v, old)
        our = fake.call(lambda t: old if ours(t) is None else ours(t), v)
        rows[k] = {"input": v, "head": head, "patched": pat, "ours": our,
                   "patched_differs": pat != head, "ours_differs": our != head}
    sha = lambda p: hashlib.sha256(open(p, "rb").read()).hexdigest()[:16]  # noqa: E731
    ace_head = subprocess.run(["git", "-C", os.path.dirname(OURS), "rev-parse", "HEAD"],
                              capture_output=True, text=True).stdout.strip()
    return {"sources": {"patched": {"path": PATCHED, "sha256": sha(PATCHED)},
                        "ours": {"path": OURS, "sha256": sha(OURS), "ace_commit": ace_head,
                                 "function": "opened('cheatsheet')"}},
            "rows": rows}


def main():
    lm = LanguageModel
    head = lambda **funcs: fake.header(REPO, funcs)  # noqa: E731
    fake.write("dc", "prompts", head(advanced_generate=lm.advanced_generate, generate=lm.generate,
                                     prompts="prompts/"), prompts())
    fake.write("dc", "parsers", head(extract_cheatsheet=extractor.extract_cheatsheet,
                                     extract_answer=extractor.extract_answer), parsers())
    fake.write("dc", "evals", head(eval_equation_balancer=evaluation.eval_equation_balancer,
                                   eval_for_multiple_choice=evaluation.eval_for_multiple_choice,
                                   eval_for_exact_matching_with_no_punctuation=evaluation.eval_for_exact_matching_with_no_punctuation),
               evals())
    fake.write("dc", "memory", head(advanced_generate=lm.advanced_generate), memory())
    fake.write("dc", "loop", head(advanced_generate=lm.advanced_generate, run_benchmark="run_benchmark.py:232"), loop())
    fake.write("dc", "cheatsheet_compare", head(extract_cheatsheet=extractor.extract_cheatsheet), cheatsheet_compare())


if __name__ == "__main__":
    main()
