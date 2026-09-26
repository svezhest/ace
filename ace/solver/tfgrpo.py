"""Решатель TF-GRPO — агент апстрима целиком (youtu-agent: configs/agents/practice/math_agent.yaml, SimpleAgent на
openai-agents; промпты tfgrpo_agent.j2, tfgrpo_answer_dapo.j2, tfgrpo_problem.j2 дословно).

    обучение    агент rollout: инструкции без опытов, в user — задача с опытами (PROBLEM_WITH_EXPERIENCE_TEMPLATE,
                до первого батча — "None"); T = 0.7 (rollout_temperature), top_p 0.95
    тест        итоговый агент (_create_agent_config_with_experiences): опыты «[G0]. ...» — в конце инструкций,
                в user — задача как есть; T = 0.3, top_p 0.95; при пустой библиотеке агент остаётся при 0.7
                (model_copy апстрима поверхностный, температуру rollout возвращают только вместе с опытами)
    разговор    Runner openai-agents над Chat Completions: tools = [execute_python_code], вызовы исполняет ядро
                в песочнице (env/tfgrpo.py), вывод — сообщением tool; ответ без вызовов — итог; на 50-м ходу к
                запросу дописана просьба ответить без инструментов (DummyContextManager), дальше — попытка заново,
                до 3 раз (rollout_with_semaphore), после — попытка без траектории
    траектория  repr списка сообщений без системного (items_to_messages(to_input_list())): её видит сводка

Инструкции агента: у dapo — math_agent.yaml дословно; у задач стенда (S2) — системный промпт задачи, тот же текст
про код и вместо формата <answer> инструкция задачи (ответ — строка FINAL ANSWER)."""
from .. import prompts, render
from ..env.tfgrpo import DEFAULT_TIMEOUT, Kernel
from ..loop import Prompt, Solver
from ..model import Call, Reply, messages
from ..render import TFGRPO
from ..tasks import final_answer, variant
from . import OwnSolver

TEMPLATE = prompts.load("tfgrpo_agent")
PROBLEM = prompts.load("tfgrpo_problem")
INTRO = "\n\n" + prompts.text("tfgrpo_experiences_intro")
LAST_TURN = {"role": "user", "content": prompts.text("tfgrpo_last_turn")}
# схема инструмента, как её шлёт openai-agents (FunctionTool python_executor апстрима)
TOOL = {"type": "function", "function": {
    "name": "execute_python_code", "description": TFGRPO.tool_description(), "strict": False,
    "parameters": {"type": "object", "title": "execute_python_code_args", "required": ["code"], "properties": {
        "code": {"type": "string", "title": "Code", "description": TFGRPO.code_description()},
        "timeout": {"type": "integer", "title": "Timeout", "default": DEFAULT_TIMEOUT,
                    "description": TFGRPO.timeout_description()}}}}}
ROLLOUT_TEMPERATURE = 0.7   # rollout_temperature
TEMPERATURE = 0.3           # итоговый агент
TOP_P = 0.95
MAX_TURNS = 50
RETRIES = 3                 # rollout_with_semaphore


def instructions(task):
    if variant("tfgrpo", task) == "math":
        return TEMPLATE.fill(role="", answer=prompts.text("tfgrpo_answer_dapo"))
    return TEMPLATE.fill(role=task.system + "\n\n", answer=task.instr)


def whole(text):
    return text


def answer(task):
    """Ответ решателя: у dapo весь итоговый ответ (формат апстрима <answer>\\boxed{}; в зачёт у dapo и так весь
    ответ — tasks.WHOLE_REPLY), у задач стенда — строка FINAL ANSWER."""
    return whole if variant("tfgrpo", task) == "math" else final_answer


def tool_call(call):
    """Вызов инструмента в истории, как его пишет openai-agents: пустые аргументы — "{}"."""
    function = {"name": call["function"]["name"], "arguments": call["function"]["arguments"] or "{}"}
    return {"id": call["id"], "type": "function", "function": function}


class Failed(Exception):
    """Попытка агента упала: MaxTurnsExceeded или вызов чужого инструмента (ModelBehaviorError)."""


def converse(model, history, params, tool):
    """Ходы агента: -> (сообщения после системного, итоговый текст, обрыв по длине)."""
    history = list(history)
    for turn in range(1, MAX_TURNS + 1):
        request = history + [LAST_TURN] if turn == MAX_TURNS else list(history)
        msg, finish = model.message(request, params)
        content = msg.get("content") or None
        calls = msg.get("tool_calls") or []
        if content is not None or calls:        # сообщение без текста и без вызовов в историю не идёт
            message = {"role": "assistant", "content": content}
            if calls:
                message["tool_calls"] = [tool_call(c) for c in calls]
            history.append(message)
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


class Agent(OwnSolver):
    def prompt(self, ex, memory, item, k):
        recs = memory.records()
        if ex.training:
            system = instructions(ex.task)
            user = PROBLEM.fill(problem=item["question"], experiences=render.experiences(recs))
            temperature = ROLLOUT_TEMPERATURE
        else:
            system = instructions(ex.task)
            temperature = ROLLOUT_TEMPERATURE
            if recs:
                system += INTRO + render.experiences(recs)
                temperature = TEMPERATURE
            user = item["question"]
        params = {"temperature": temperature, "top_p": TOP_P, "tools": [TOOL]}

        def call(note):
            return Call(messages(user, system), params)
        return Prompt(shown=[r.id for r in recs], temperature=temperature,
                      solver=Solver(call, answer(ex.task), talk))


AGENT = Agent()
