"""Бэкенд pydantic-ai: один агент на вызов, инструменты и схема ответа передаются явно.
С on_step прогон идёт по одному запросу к модели: после шага с инструментами on_step(новые шаги) может
вернуть Patch, и он применяется к истории до следующего запроса."""
import pydantic_ai
from pydantic_ai import Agent, Tool, UsageLimits, capture_run_messages
from pydantic_ai.exceptions import UnexpectedModelBehavior, UsageLimitExceeded
from pydantic_ai.messages import (ModelRequest, ModelResponse, RetryPromptPart, SystemPromptPart, TextPart, ToolCallPart,
                                  ToolReturnPart, UserPromptPart)
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIChatModelSettings
from pydantic_ai.providers.openai import OpenAIProvider

from .. import config, render
from . import Outcome, Reply, Step, content

# запросов сверх раундов инструментов: ответ и одна попытка исправить вывод, не прошедший схему
EXTRA_REQUESTS = 2
RETRIES = 3                 # попыток модели исправить вывод, не прошедший схему (не сетевые повторы)

pydantic_ai.BANNER_ENABLED = False     # что печатать, решает стенд


def apply(messages, patch):
    """Patch к истории: последнее сообщение — запрос с результатами инструментов шага."""
    if patch.system is not None:
        for m in messages:
            if not isinstance(m, ModelRequest):
                continue
            for part in m.parts:
                if isinstance(part, SystemPromptPart):
                    part.content = patch.system
    last = messages[-1]
    if patch.tool_result:
        results = [part for part in last.parts
                   if isinstance(part, (ToolReturnPart, RetryPromptPart)) and isinstance(part.content, str)]
        if results:
            results[-1].content += "\n\n" + patch.tool_result
        else:
            last.parts.append(UserPromptPart(patch.tool_result))
    if patch.append:
        last.parts.append(UserPromptPart(patch.append))


def to_pydantic_ai(messages):
    """Сообщения вызова -> (системный промпт, история pydantic-ai до последнего сообщения, последнее — user).
    При непустой истории системный промпт входит в её первый запрос: pydantic-ai ставит его только без истории."""
    system = "\n\n".join(content(m) for m in messages if m["role"] == "system")
    turns = [m for m in messages if m["role"] != "system"]
    history = []
    for m in turns[:-1]:
        if m["role"] == "user":
            history.append(ModelRequest([UserPromptPart(content(m))]))
        else:
            history.append(ModelResponse([TextPart(content(m))]))
    if history and system and isinstance(history[0], ModelRequest):
        history[0].parts.insert(0, SystemPromptPart(system))
    return system, history, content(turns[-1])


class PydanticAI:
    def __init__(self, name, base_url):
        self.llm = OpenAIChatModel(name, provider=OpenAIProvider(base_url=base_url, api_key=config.API_KEY))
        self.calls = self.prompt_tokens = self.completion_tokens = 0

    def ask(self, call):
        system, history, user = to_pydantic_ai(call.messages)
        history = (call.history or []) + history
        history = history or None       # pydantic-ai различает пустую историю и её отсутствие
        output = call.reader.schema or str
        limit = call.rounds + EXTRA_REQUESTS
        if call.on_step is None:
            result, messages, outcome = self.request(system, user, history, output, call, limit)
        else:
            result, messages, outcome = self.stepwise(system, user, history, output, call, limit)
        responses = [m for m in messages if isinstance(m, ModelResponse)]
        out = result if call.reader.schema else call.reader.read(result)
        return Reply(out, render.transcript(messages), truncated=any(m.finish_reason == "length" for m in responses),
                     steps=steps(messages), outcome=outcome, messages=messages,
                     raw=result if isinstance(result, str) else None)

    def stepwise(self, system, user, history, output, call, limit):
        """Шаговый режим — для тех, кто вмешивается посреди попытки: показ после ошибки (урок в конец истории) и
        SCOPE (правило, выученное на шаге, переписывает системный промпт). Прогон идёт по одному запросу к модели;
        после шага с инструментами on_step получает новые шаги и может вернуть Patch — он применяется к истории до
        следующего запроса. -> (ответ, все сообщения, Outcome)."""
        seen = 0                # шагов уже отдано on_step
        result, messages, outcome = self.request(system, user, history, output, call, 1)
        for n in range(1, limit + 1):
            new = steps(messages)[seen:]
            seen += len(new)
            if outcome is not Outcome.step:
                break
            patch = call.on_step(new) if new else None
            if patch:
                apply(messages, patch)
                if patch.system is not None:
                    system = patch.system
            if n == limit:
                break
            result, messages, outcome = self.request(system, None, messages, output, call, 1)
        return result, messages, outcome

    def request(self, system, user, history, output, call, limit):
        """До limit запросов; -> (ответ или None, все сообщения, Outcome). user — новое сообщение после history
        (None: история уже кончается запросом). Сообщения сохраняются и при сбое: траектория и токены не теряются.
        Пустой системный промпт не отправляется: апстримы шлют промпт одним сообщением user."""
        # отбивка инструмента (ModelRetry) — обычный шаг: разговор кончается по раундам, а не на 4-й отбивке подряд
        tools = [Tool(t, max_retries=max(RETRIES, call.rounds), description=getattr(t, "description", None))
                 for t in call.tools]
        agent = Agent(self.llm, system_prompt=system or (), output_type=output, tools=tools, retries=RETRIES)
        result, outcome = None, Outcome.answer
        with capture_run_messages() as messages:
            try:
                result = agent.run_sync(user, message_history=history, deps=call.deps,
                                        usage_limits=UsageLimits(request_limit=limit), model_settings=settings(call.params)).output
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


SETTINGS = {"max_completion_tokens": "max_tokens", "reasoning_effort": "openai_reasoning_effort", "stop": "stop_sequences"}
KNOWN = set(OpenAIChatModelSettings.__annotations__)


def settings(params):
    """Параметры вызова -> настройки pydantic-ai (предел генерации у них один, max_tokens; reasoning_effort —
    openai_reasoning_effort). Параметр, которого pydantic-ai не знает, он молча выбросил бы — ошибка."""
    out = {}
    for k, v in params.items():
        if SETTINGS.get(k, k) not in KNOWN:
            raise ValueError(f"параметр вызова {k} бэкенд pydantic-ai не передаст модели")
        out[SETTINGS.get(k, k)] = v
    return out


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
