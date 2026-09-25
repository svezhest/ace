"""Модель через pydantic-ai: один агент на вызов, tools и схема ответа передаются явно.
С on_step прогон идёт по одному запросу к модели: после шага с инструментами on_step(новые шаги) может
вернуть Patch, и он применяется к истории до следующего запроса."""
import os
os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")
from dataclasses import dataclass
from enum import Enum
from typing import NamedTuple

from pydantic_ai import Agent, UsageLimits, capture_run_messages
from pydantic_ai.exceptions import UnexpectedModelBehavior, UsageLimitExceeded
from pydantic_ai.messages import (ModelRequest, ModelResponse, RetryPromptPart, SystemPromptPart, ToolCallPart, ToolReturnPart,
                                  UserPromptPart)
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from . import config, render

# запросов сверх раундов инструментов: ответ и одна попытка исправить вывод, не прошедший схему
EXTRA_REQUESTS = 2
RETRIES = 3                 # попыток модели исправить невалидный вызов или вывод (не сетевые повторы)


class Outcome(Enum):
    """Чем кончился запрос к модели."""
    answer = "answer"       # модель ответила
    step = "step"           # кончился лимит запросов: шаг сделан, ответа ещё нет
    broken = "broken"       # модель сломалась: вывод не прошёл схему после всех попыток (UnexpectedModelBehavior)


class Step(NamedTuple):
    """Шаг попытки: вызов инструмента и его результат (отбивка — «Error: ...»)."""
    tool: str
    args: str
    result: str

    @property
    def failed(self):
        """Отбивка: traceback исполнения или ошибка вызова (ModelRetry, аргументы не той формы)."""
        return "Traceback" in self.result or self.result.startswith("Error")


@dataclass
class Patch:
    """Вмешательство посреди попытки, до следующего запроса к модели.
    system — новый системный промпт целиком (SCOPE, как в апстриме; префикс истории меняется);
    append — сообщение в конец истории, после результатов инструментов (префикс цел);
    tool_result — текст к результату последнего инструмента (урок прямо в отбивке)."""
    system: str = None
    append: str = None
    tool_result: str = None

    def merge(self, other):
        """Два вмешательства одного шага: системный промпт — последний, дописывания — подряд."""
        join = lambda a, b: "\n\n".join(x for x in (a, b) if x) or None
        return Patch(other.system if other.system is not None else self.system,
                     join(self.append, other.append), join(self.tool_result, other.tool_result))


def apply(messages, patch):
    """Patch к истории: последнее сообщение — запрос с результатами инструментов шага."""
    if patch.system is not None:
        for p in (p for m in messages if isinstance(m, ModelRequest) for p in m.parts):
            if isinstance(p, SystemPromptPart):
                p.content = patch.system
    last = messages[-1]
    if patch.tool_result:
        results = [p for p in last.parts if isinstance(p, (ToolReturnPart, RetryPromptPart)) and isinstance(p.content, str)]
        if results:
            results[-1].content += "\n\n" + patch.tool_result
        else:
            last.parts.append(UserPromptPart(patch.tool_result))
    if patch.append:
        last.parts.append(UserPromptPart(patch.append))


@dataclass
class Reply:
    output: object          # str или объект схемы; None, если модель не справилась
    text: str               # вся траектория текстом: ответы, вызовы tools, их результаты
    truncated: bool
    steps: list             # шаги: Step(имя, аргументы, результат)
    outcome: Outcome = Outcome.answer
    messages: list = None   # вся история: продолжить разговор (run(history=...))


class Model:
    def __init__(self, name=None, max_tokens=None, base_url=None):
        self.name = name or config.MODEL
        self.max_tokens = max_tokens or config.MAX_TOKENS
        self.llm = OpenAIChatModel(self.name, provider=OpenAIProvider(base_url=base_url or config.OPENAI_BASE_URL,
                                                                      api_key=config.API_KEY))
        self.calls = self.prompt_tokens = self.completion_tokens = 0

    def run(self, system, user, output=str, tools=(), deps=None, rounds=0, temperature=0, max_tokens=None, on_step=None,
            top_p=None, history=None):
        """history — сообщения прошлого прогона (Reply.messages): user продолжает тот же разговор (MCE: просьба
        мета-агенту дописать SKILL.md)."""
        settings = {"temperature": temperature, "max_tokens": max_tokens or self.max_tokens}
        if top_p is not None:
            settings["top_p"] = top_p
        limit = rounds + EXTRA_REQUESTS
        if on_step is None:
            result, messages, outcome = self.request(system, user, history, output, tools, deps, limit, settings)
        else:
            # ШАГОВЫЙ РЕЖИМ. Нужен тем, кто вмешивается посреди попытки: показу после ошибки (урок в конец истории)
            # и SCOPE (правило, выученное на шаге, переписывает системный промпт). Прогон идёт по одному запросу;
            # после шага с инструментами on_step получает новые шаги и может вернуть Patch, он применяется к
            # истории до следующего запроса. История сообщений переходит из запроса в запрос.
            result, messages = None, None
            for _ in range(limit):
                before = steps(messages or [])
                result, messages, outcome = self.request(system, None if messages else user, messages, output, tools, deps, 1,
                                                         settings)
                new = steps(messages)[len(before):]
                if outcome is not Outcome.step:
                    break
                patch = on_step(new) if new else None
                if patch:
                    apply(messages, patch)
                    if patch.system is not None:
                        system = patch.system
        responses = [m for m in messages if isinstance(m, ModelResponse)]
        return Reply(result, render.transcript(messages), any(m.finish_reason == "length" for m in responses), steps(messages),
                     outcome, messages)

    def request(self, system, user, history, output, tools, deps, limit, settings):
        """До limit запросов; -> (ответ или None, все сообщения, Outcome). user — новое сообщение после history
        (None: история уже кончается запросом). Сообщения сохраняются и при сбое: траектория и токены не теряются."""
        agent = Agent(self.llm, system_prompt=system, output_type=output, tools=tools, retries=RETRIES)
        result, outcome = None, Outcome.answer
        with capture_run_messages() as messages:
            try:
                result = agent.run_sync(user, message_history=history, deps=deps,
                                        usage_limits=UsageLimits(request_limit=limit), model_settings=settings).output
            except UsageLimitExceeded:
                outcome = Outcome.step
            except UnexpectedModelBehavior:
                outcome = Outcome.broken
        messages = list(messages)
        responses = [m for m in messages[len(history or []):] if isinstance(m, ModelResponse)]
        self.calls += len(responses)
        self.prompt_tokens += sum(m.usage.input_tokens for m in responses)
        self.completion_tokens += sum(m.usage.output_tokens for m in responses)
        return result, messages, outcome

    def one(self, system, user, temperature=0, max_tokens=None):
        return self.run(system, user, temperature=temperature, max_tokens=max_tokens)

    def usage(self):
        return dict(calls=self.calls, prompt_tokens=self.prompt_tokens, completion_tokens=self.completion_tokens)


def steps(messages):
    """Шаги: вызов инструмента и результат; отбивка (ModelRetry или ошибки валидации аргументов) —
    результат «Error: ...»."""
    calls, out = {}, []
    for m in messages:
        for p in m.parts:
            if isinstance(p, ToolCallPart):
                calls[p.tool_call_id] = (p.tool_name, p.args_as_json_str())
            elif isinstance(p, ToolReturnPart) and p.tool_call_id in calls:
                out.append(Step(*calls[p.tool_call_id], str(p.content)))
            elif isinstance(p, RetryPromptPart) and p.tool_call_id in calls:
                out.append(Step(*calls[p.tool_call_id], render.retry_error(p.content)))
    return out
