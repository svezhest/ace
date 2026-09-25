"""Шаблоны Jinja2 дают модели ровно то же, что старые промпты со своим синтаксисом подстановки
(format, positional, brackets, jinja из yaml) и старые строки в коде. Старые тексты — с тега pre-rewrite."""
import json
import subprocess

import jinja2
import jinja2.meta
import pytest
import yaml

from ace import prompts, render

OLD = "pre-rewrite"
OLD_DIR = "ace/methods/prompts"


def old_file(name):
    try:
        return subprocess.run(["git", "show", f"{OLD}:{OLD_DIR}/{name}"], capture_output=True, text=True, check=True).stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        pytest.skip(f"нет тега {OLD}")


def old_files():
    out = subprocess.run(["git", "ls-tree", "--name-only", f"{OLD}:{OLD_DIR}"], capture_output=True, text=True).stdout
    return [f for f in out.split() if f.endswith(".txt")]


def fields(name):
    source = prompts.ENV.loader.get_source(prompts.ENV, f"{name}.j2")[0]
    return sorted(jinja2.meta.find_undeclared_variables(prompts.ENV.parse(source)))


def value(field):
    """Значение с фигурными и квадратными скобками и переводом строки: подстановка не должна их трогать."""
    return 0.8765 if field == "initial_confidence" else f"<{field}> {{\"a\": [1]}} {{x}}\nsecond line %s"


REFLECTOR = ["question", "reasoning_trace", "predicted_answer", "ground_truth", "environment_feedback", "bullets_used"]
POSITIONAL = {"ace_reflector.txt": REFLECTOR, "ace_reflector_nogt.txt": [n for n in REFLECTOR if n != "ground_truth"]}
BRACKETS = ("dc_synth.txt", "dc_curator.txt")
RAW = ("dc_note.txt", "evolib_subtasks.txt")        # брались текстом, без подстановки


def old_render(file, text, values):
    if file in RAW:
        return text
    if file in POSITIONAL:
        return text.format(*[values[n] for n in POSITIONAL[file]])
    if file in BRACKETS:
        for k, v in values.items():
            text = text.replace(f"[[{k}]]", str(v))
        return text
    return text.format(**values)


@pytest.mark.parametrize("file", old_files() or ["(нет тега)"])
def test_upstream_prompt(file):
    text = old_file(file)
    name = file.removesuffix(".txt")
    values = {f: value(f) for f in fields(name)}
    assert prompts.load(name).fill(values) == old_render(file, text, values)


def test_tfgrpo_yaml():
    for key, text in yaml.safe_load(old_file("tfgrpo.yaml")).items():
        name = f"tfgrpo_{key.lower()}"
        values = {f: value(f) for f in fields(name)}
        assert prompts.load(name).fill(values) == jinja2.Template(text).render(**values), key


# короткие строки, которые были в коде; ожидаемое — старый текст дословно
INLINE = {
    "solver_used": "Right before the final answer line, write one line 'USED: <ids of the memory bullets "
                   "you actually relied on, comma-separated, or none>'.",
    "judge_system": "You are a strict grader.",
    "sandbox_hint": "You may run Python with run_python before giving the final answer.",
    "reflector_system": "You are a reflector.",
    "curator_system": "You are a curator.",
    "selector_system": "You are a selector.",
    "mce_base_system": "You are a context engineer working with file tools.",
    "reflect_free_form": "Write freely.",
    "memory_head": "What you learned so far:\n",
    "hook_intro": "Known fix for this error:\n",
    "scope_strategic_intro": "## Strategic Guidelines (Learned Best Practices):\nThese are high-confidence rules learned from previous tasks:\n\n",
    "scope_guideline": "## Learned Guideline:\n",
    "evolib_skills_intro": "Here are some subtask solutions which you may reuse or adapt for the problem:\n",
    "evolib_insights_intro": "Here are some insights that may help you solve the problem:\n",
    "tfgrpo_experiences_intro": "When solving problems, you MUST first carefully read and understand the helpful instructions and experiences:\n",
    "tfgrpo_objective_formula": "input: A financial question with a formula to apply\noutput: A step-by-step reasoning process that leads to the numeric answer",
    "tfgrpo_objective_finer": "input: A financial text with numbered entities and a list of XBRL tags\noutput: A step-by-step reasoning process that leads to one tag per entity",
    "tfgrpo_objective_meb": "input: An equation with missing operators\noutput: A step-by-step reasoning process that leads to the equation with the operators filled in",
    "tfgrpo_objective_gpqa": "input: A multiple-choice question in physics, chemistry or biology\noutput: A step-by-step reasoning process that leads to the option letter",
    "tfgrpo_learning": "Help the agent to improve the solving capability on these questions by extracting general and concise guidelines.",
    "mce_no_iterations": "No previous iterations (this is iteration 1, iter0 is baseline). Design an initial skill based on the task.",
    "placebo": "\n".join(f"[r{i}] Read the question carefully and check units before answering." for i in range(1, 9)),
    "ace_no_bullets": "(No bullets used by generator)",
    "task_finer_system": "You are an XBRL expert.",
    "task_formula_system": "You are a financial analyst.",
    "task_meb_system": "You are a careful math assistant.",
    "task_gpqa_system": "You are a careful expert in physics, chemistry and biology.",
    "task_finer_instr": "For each numbered entity choose the single best tag from the given list, copying it exactly. "
                        "Reason briefly, then give the final answer as one line: 'FINAL ANSWER: tag1,tag2,...' "
                        "(one tag per entity, in order, comma-separated, nothing else on that line).",
    "task_formula_instr": "Answer the financial question using the given formula. The answer must be a plain floating point "
                          "number (no units, no currency signs, no thousands separators), rounded to two decimals. "
                          "Reason briefly, then give the final answer as one line: 'FINAL ANSWER: <number>'.",
    "task_meb_instr": "Below is an equation with missing operators. Your task is to fill in the blanks with the correct "
                      "mathematical operators: +, -, *, or /. Ensure that the equation is correct once the operators are added. "
                      "The operators should be placed in the sequence they appear from left to right. Include the full equation "
                      "with the operators filled in. For instance, for the equation 1 ? 2 ? 3 = 6, the correct answer is 1 + 2 + 3 = 6.\n"
                      "Reason step by step, then give the final equation as one line: 'FINAL ANSWER: <equation>'.",
    "task_gpqa_instr": "Answer the multiple-choice question below. Reason carefully, then give the final answer as the "
                       "option letter in parentheses on the last line after 'FINAL ANSWER:', e.g. FINAL ANSWER: (B).",
}


@pytest.mark.parametrize("name", INLINE)
def test_inline(name):
    assert prompts.text(name) == INLINE[name]


def test_judge():
    old = """Check the solution below. Recompute the key quantities yourself and compare with the solution's final answer.
End with one line: VERDICT: correct  or  VERDICT: wrong

## Task
{question}

## Solution
{output}"""
    v = dict(question=value("question"), output=value("output"))
    assert prompts.text("judge", **v) == old.format(**v)


def test_hook_raw():
    old = lambda name, args: f"Earlier the same error was followed by a call that worked:\n{name} {args}"
    assert prompts.text("hook_raw", name="run_python", args='{"code": "1"}') == old("run_python", '{"code": "1"}')


@pytest.mark.parametrize("correct", [True, False, None])
def test_ace_feedback(correct):
    old = "Predicted answer matches ground truth" if correct else "Predicted answer does not match ground truth"
    assert prompts.text("ace_environment_feedback", correct=correct) == old


@pytest.mark.parametrize("always", [(), ("constraint",)])
@pytest.mark.parametrize("rules", ["", "- a\n- b"])
def test_catalog(always, rules):
    listing = "skills/r1  when dividing"
    old = ""
    if always:
        old += "Rules:\n" + (rules or "(none)") + "\n\n"
    old += "Entries you can read with read(path):\n" + listing
    assert prompts.text("catalog", always=bool(always), rules=rules, listing=listing) == old


@pytest.mark.parametrize("strategic", ["", "\nintro\n### General:\n- rule"])
@pytest.mark.parametrize("tactical", [[], ["one"], ["one", "two {x}"]])
def test_scope_rules_context(strategic, tactical):
    old = ("\n=== STRATEGIC RULES (Cross-task, persistent): ===\n" + (strategic or "No strategic rules yet.")
           + "\n\n=== TACTICAL RULES (Current task only): ===\n"
           + ("".join(f"{i}. {r}\n" for i, r in enumerate(tactical, 1)) or "No tactical rules yet.\n"))
    assert prompts.text("scope_rules_context", strategic=strategic, tactical=tactical) == old


def old_batch_table(records, ops):
    if not ops:
        return "No batch operations."
    dump = lambda op: json.dumps(op, ensure_ascii=False, indent=2)
    out = []
    for id, text in records:
        related = [op for op in ops if op.get("id") == id]
        out.append(f"Experience {id}:\nContent: {text}\n"
                   + ("Related Operations:\n" + "\n".join(map(dump, related)) if related else "No related operations."))
    loose = [op for op in ops if not op.get("id")]
    if loose:
        out.append("Operations without specific Experience ID:\n" + "\n".join(map(dump, loose)))
    return "\n\n".join(out)


OPS = [dict(operation="UPDATE", id="G0", content="new"), dict(operation="ADD", id=None, content="x {y}"),
       dict(operation="DELETE", id="G0", content="")]


@pytest.mark.parametrize("records", [[], [("G0", "one")], [("G0", "one"), ("G1", "two")]])
@pytest.mark.parametrize("ops", [[], OPS[:1], OPS[1:2], OPS])
def test_batch_table(records, ops):
    from ace.memory import Lessons
    memory = Lessons()
    for _, text in records:
        memory.add(text)
    assert render.batch_table(memory.records(), ops) == old_batch_table(records, ops)
