"""Показ TF-GRPO — агент апстрима целиком (youtu-agent: configs/agents/practice/math_agent.yaml, SimpleAgent на
openai-agents; промпты tfgrpo_agent.j2, tfgrpo_answer_dapo.j2, tfgrpo_problem.j2 дословно).

    обучение    агент rollout: инструкции без опытов, в user — задача с опытами (PROBLEM_WITH_EXPERIENCE_TEMPLATE,
                до первого батча — "None"); T = 0.7 (rollout_temperature), top_p 0.95
    тест        итоговый агент (_create_agent_config_with_experiences): опыты «[G0]. ...» — в конце инструкций,
                в user — задача как есть; T = 0.3, top_p 0.95; при пустой библиотеке агент остаётся при 0.7
                (model_copy апстрима поверхностный, температуру rollout возвращают только вместе с опытами)
    разговор    Runner openai-agents над Chat Completions: tools = [execute_python_code], вызовы исполняет ядро
                в песочнице (env/kernel.py), вывод — сообщением tool; ответ без вызовов — итог; на 50-м ходу к
                запросу дописана просьба ответить без инструментов (DummyContextManager), дальше — попытка заново,
                до 3 раз (rollout_with_semaphore), после — попытка без траектории
    траектория  repr списка сообщений без системного (items_to_messages(to_input_list())): её видит сводка

Инструкции агента: у dapo — math_agent.yaml дословно; у задач стенда (S2) — системный промпт задачи, тот же текст
про код и вместо формата <answer> инструкция задачи (ответ — строка FINAL ANSWER)."""
from .. import prompts, render
from ..env import sandbox
from ..loop import Prompt, Solver
from ..model import Call, Reply, messages
from ..tasks import final_answer
from . import Show

TEMPLATE, PROBLEM = prompts.load("tfgrpo_agent"), prompts.load("tfgrpo_problem")
INTRO = "\n\n" + prompts.text("tfgrpo_experiences_intro")
LAST_TURN = {"role": "user", "content": prompts.text("tfgrpo_last_turn")}
TOOL = {"type": "function", "function": {
    "name": "execute_python_code", "description": "Executes Python code and returns the output.", "strict": False,
    "parameters": {"type": "object", "title": "execute_python_code_args", "required": ["code"], "properties": {
        "code": {"type": "string", "title": "Code", "description": "The Python code to execute."},
        "timeout": {"type": "integer", "title": "Timeout", "default": 30,
                    "description": "The execution timeout in seconds. Defaults to 30."}}}}}
ROLLOUT_TEMPERATURE, TEMPERATURE, TOP_P = 0.7, 0.3, 0.95
MAX_TURNS = 50
RETRIES = 3                 # rollout_with_semaphore
Kernel = sandbox.Kernel


def instructions(task):
    if task.name == "dapo":
        return TEMPLATE.fill(role="", answer=prompts.text("tfgrpo_answer_dapo"))
    return TEMPLATE.fill(role=task.system + "\n\n", answer=task.instr)


def answer(task):
    """Ответ в зачёт: у dapo весь итоговый ответ (его судит math_verify), у задач стенда — строка FINAL ANSWER."""
    return (lambda text: text) if task.name == "dapo" else final_answer


class Failed(Exception):
    """Попытка агента упала: MaxTurnsExceeded или вызов чужого инструмента (ModelBehaviorError)."""


def converse(model, history, params, tool):
    """Ходы агента: -> (сообщения после системного, итоговый текст, обрыв по длине)."""
    history = list(history)
    for turn in range(1, MAX_TURNS + 1):
        msg, finish = model.message(history + [LAST_TURN] * (turn == MAX_TURNS), params)
        content, calls = msg.get("content") or None, msg.get("tool_calls") or []
        # сообщение без текста и без вызовов в историю не идёт; пустые аргументы в истории — "{}"
        if content is not None or calls:
            history.append({"role": "assistant", "content": content, **({"tool_calls": [
                {"id": c["id"], "type": "function",
                 "function": {"name": c["function"]["name"], "arguments": c["function"]["arguments"] or "{}"}}
                for c in calls]} if calls else {})})
        if not calls:
            return history[1:], content or "", finish == "length"
        for c in calls:
            if c["function"]["name"] != TOOL["function"]["name"]:
                raise Failed(c["function"]["name"])
            history.append({"role": "tool", "tool_call_id": c["id"], "content": tool(c["function"]["arguments"])})
    raise Failed(f"max turns {MAX_TURNS}")


def talk(model, call):
    """Попытка агента; ядро песочницы — на попытку. Все попытки упали — траектории нет."""
    for _ in range(RETRIES):
        kernel = Kernel()
        try:
            trajectory, final, cut = converse(model, call.messages, call.params, kernel.call)
            return Reply(final, repr(trajectory), cut)
        except Failed:
            continue
        finally:
            kernel.close()
    return Reply("", "")


class Agent(Show):
    def prompt(self, ex, memory, item, k):
        recs = memory.records()
        if ex.training:
            system = instructions(ex.task)
            user = PROBLEM.fill(problem=item["context"], experiences=render.experiences(recs))
            temperature = ROLLOUT_TEMPERATURE
        else:
            system = instructions(ex.task) + (INTRO + render.experiences(recs) if recs else "")
            user, temperature = item["context"], TEMPERATURE if recs else ROLLOUT_TEMPERATURE
        params = {"temperature": temperature, "top_p": TOP_P, "tools": [TOOL]}

        def call(note):
            return Call(messages(user, system), params)
        return Prompt(shown=[r.id for r in recs], temperature=temperature, top_p=TOP_P,
                      solver=Solver(call, answer(ex.task), talk))


AGENT = Agent()
