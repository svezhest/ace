"""ACE апстрима (ace/ace/ace.py, eval/finance/data_processor.py): вход задачи и параметры вызовов генератора,
рефлектора и куратора."""
from .. import prompts
from ..tasks import variant

MAX_TOKENS = 4096           # --max_tokens апстрима


def ace_params():
    """Параметры вызова генератора, рефлектора и куратора апстрима (timed_llm_call при api_provider openai)."""
    return dict(temperature=0.0, max_completion_tokens=MAX_TOKENS)


FORMULA_NOTE = prompts.text("ace_formula_note")


def ace_input(task, text):
    """(context, question) из входа задачи, как DataProcessor.process_task_data апстрима. formula
    (parse_context_and_question_formula): вопрос между «Question: » и «. Answer:», без обрамляющих кавычек и с
    припиской про число, context пуст — формула из входа не попадает никуда. Остальные
    (parse_instruction_and_input): при «Instruction: ... Input: ... Answer: » context — текст после «Input: »,
    вопрос — инструкция; иначе context пуст, вопрос — весь вход."""
    if variant("ace", task) == "formula":
        if "Question: " not in text or ". Answer:" not in text:
            return "", text
        question = text.split("Question: ", 1)[1].split(". Answer:")[0].strip()
        if question.startswith('"') and question.endswith('"'):
            question = question[1:-1]
        return "", question + FORMULA_NOTE
    if "Input: " not in text or "Instruction: " not in text:
        return "", text
    instruction = text.split("Input: ")[0].strip().split("Instruction: ")[1].strip()
    return text.split("Input: ")[1].split("Answer: ")[0].strip(), instruction
