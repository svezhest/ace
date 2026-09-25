"""Решатель Dynamic Cheatsheet: генератор апстрима целиком (dynamic-cheatsheet: language_model.py advanced_generate и
generate, run_benchmark.py; промпты dc_generator.j2, dc_synth.j2, dc_note.j2 дословно).

Generator — решатель попытки: одно сообщение user из generator_prompt.txt с cheatsheet и входом задачи, как его
строит run_benchmark (dc_input: «Question #k:», у meb — вступление задачи); T = 0.0, max_completion_tokens 2048;
ответ в зачёт — extract_answer (parse.dc_answer). С кодом (dc_code) — разговор generate: блок ```python перед
«EXECUTE CODE!» исполняется в песочнице (run_block), вывод и просьба продолжить — сообщениями, до 3 продолжений.

Что стоит в [[CHEATSHEET]]:
    cumulative  dc: весь текст памяти, до первой записи — "(empty)"
    retrieval   top-3 прошлых пары по близости вопросов (embed.similarity) в оформлении PREVIOUS SOLUTIONS, самая
                похожая последней (dc_retrieval, Dynamic_Retrieval)
    synthesis   dc_rs: из retrieval и прошлого cheatsheet модель синтезирует cheatsheet под вопрос, и на первом
                вопросе тоже (пары "(empty)"); без блока <cheatsheet> генератор видит сами пары, и они же
                сохраняются как cheatsheet (extract_cheatsheet(old_cheatsheet=пары), как в апстриме)
    history     все прошлые пары подряд (dc_history, FullHistoryAppending)"""
from .. import parse, prompts, render
from ..env import sandbox
from ..loop import Prompt, Solver
from ..upstream.dc import CHEATSHEET, MAX_TOKENS, TOKENS, dc_params
from ..extract import INPUT, SHEET
from ..model import Call, Reply, messages
from ..tasks import variant
from ..show import TopK, Whole
from . import OwnSolver

GENERATOR = prompts.load("dc_generator")
SYNTH = prompts.load("dc_synth")
NOTE = prompts.text("dc_note")
MEB = prompts.text("dc_meb")
PROCEED = prompts.text("dc_proceed")
LAST_ROUND = prompts.text("dc_last_round")
DC = prompts.macros("dc_strings")
FLAG = DC.flag()            # после блока кода — просьба его исполнить
TOP = 3                     # --retrieve_top_k
ROUNDS = 3                  # max_depth_num_rounds generate
CODE_LIMIT = 3              # секунд на код, как execute_code_with_timeout
CODE_FILE = "/tmp/code.py"  # код исполняется файлом, как у апстрима (у него — случайное имя tempfile)


def dc_input(task, i, question):
    """Вход задачи i (с нуля), как его строит run_benchmark.py апстрима: у meb — вступление MathEquationBalancer."""
    text = DC.question(n=i + 1, text=question)
    return MEB + text if variant("dc", task) == "meb" else text


class Generator(OwnSolver):
    """Решатель DC апстрима; sheet(ex, память, item, вход) -> (текст для [[CHEATSHEET]], показанные записи)."""
    def __init__(self, sheet, code=False):
        self.sheet, self.code = sheet, code
        self.reads = READS.get(sheet, ())

    def prompt(self, ex, memory, item, k):
        question = dc_input(ex.task.name, ex.i, item["question"])
        text, recs = self.sheet(ex, memory, item, question)

        def call(note):
            return Call(messages(GENERATOR.fill(QUESTION=question, CHEATSHEET=text)), dc_params())

        def talk(model, call):
            return generate(model, call, self.code)
        return Prompt(shown=[r.id for r in recs], solver=Solver(call, parse.dc_answer, talk), seen={INPUT: question, SHEET: text})


def generate(model, call, code):
    """LanguageModel.generate апстрима: пустой ответ — "(No response generated)"; с кодом ответ, где перед FLAG
    стоит блок в ```, обрезается по FLAG, код исполняется, и разговор продолжается (в последнем раунде — с
    предупреждением); после ROUNDS продолжений последний блок с выводом дописывается ещё раз, как в апстриме.
    -> Reply: весь накопленный текст (final_output апстрима)."""
    history, final = list(call.messages), ""
    for depth in range(1, ROUNDS + 2):
        reply = model.ask(Call(list(history), call.params))
        output = reply.output or DC.no_response()
        head = output.split(FLAG)[0].strip()
        runs_code = code and FLAG in output and head.endswith("```")      # перед флагом — закрытый блок кода
        if not runs_code:
            break
        ran = run_block(head)
        current = f"{head}\n{FLAG}\n\n{ran.strip() if ran else DC.no_block()}"
        final = f"{final}\n\n{current}".strip()
        if depth > ROUNDS:
            output = current
            break
        history += [{"role": "assistant", "content": current},
                    {"role": "user", "content": PROCEED + (LAST_ROUND if depth == ROUNDS else "")}]
    text = f"{final}\n\n{output}".strip()
    return Reply(text, text, reply.truncated)


def run_block(text):
    """extract_and_run_python_code апстрима: первый блок ```python; последняя строка без print, отступа, # и
    return оборачивается в print; исполнение — в песочнице (у апстрима python3 на хосте) с тем же пределом и теми
    же сообщениями."""
    if "```python" not in text:
        return ""
    try:
        lines = text.split("```python", 1)[1].split("```", 1)[0].strip().splitlines()
        last = lines[-1].rstrip()
        if not last.startswith(("print(", "#", " ", "\t")) and "return" not in last:
            lines[-1] = f"print({last})"
        return DC.code_output(output=execute("\n".join(lines)))
    except Exception as error:
        return DC.code_error(error=error)


def execute(code):
    """execute_code_with_timeout апстрима: stdout, без него — ошибка из stderr или просьба напечатать."""
    r = sandbox.run(code, limit=CODE_LIMIT, path=CODE_FILE)
    if r["timeout"]:
        return DC.timeout()
    out, err = r["stdout"].strip(), r["stderr"].strip()
    if out:
        return out
    return DC.execution_error(stderr=err) if err else DC.no_output()


def cumulative(ex, memory, item, question):
    return memory.current(), memory.records()


RETRIEVAL = TopK(TOP, key=lambda r: r.question, layout=lambda recs, memory: render.pairs(recs, True, NOTE), empty=DC.empty())
HISTORY = Whole(layout=lambda recs, memory: render.pairs(recs, False), empty=DC.empty())


def retrieval(ex, memory, item, question):
    return RETRIEVAL.text(ex, memory, item)


def history(ex, memory, item, question):
    return HISTORY.text(ex, memory, item)


def synthesis(ex, memory, item, question):
    pairs, recs = RETRIEVAL.text(ex, memory, item)
    prompt = SYNTH.fill(PREVIOUS_INPUT_OUTPUT_PAIRS=pairs, NEXT_INPUT=question, PREVIOUS_CHEATSHEET=memory.sheet.current())
    out = ex.model.ask(Call(messages(prompt), dc_params(TOKENS * MAX_TOKENS), CHEATSHEET)).output
    return (pairs if out is None else out), recs


READS = {cumulative: ("current",), synthesis: ("sheet",)}     # что показ cheatsheet читает у памяти
