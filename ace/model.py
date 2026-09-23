"""Модель через pydantic-ai: один агент на вызов, tools и схема ответа передаются явно.
С on_step прогон идёт по одному запросу к модели: после шага с инструментами on_step(новые шаги) может
вернуть текст, и он дописывается к системному промпту до следующего запроса (события шага, хуки инжекта)."""
import os
os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")
from dataclasses import dataclass

from pydantic_ai import Agent, UsageLimits, capture_run_messages
from pydantic_ai.exceptions import UnexpectedModelBehavior, UsageLimitExceeded
from pydantic_ai.messages import (ModelRequest, ModelResponse, RetryPromptPart, SystemPromptPart, TextPart, ToolCallPart,
                                  ToolReturnPart)
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider


@dataclass
class Reply:
    output: object          # str или объект схемы; None, если модель не справилась
    text: str               # вся траектория текстом: ответы, вызовы tools, их результаты
    truncated: bool
    steps: list             # вызовы tools: (имя, аргументы, результат)


class Model:
    def __init__(self, name=None, max_tokens=None, base_url=None):
        self.name = name or os.getenv("MODEL", "ornith15-9b")
        self.max_tokens = max_tokens or int(os.getenv("MAX_TOKENS", 4096))
        self.llm = OpenAIChatModel(self.name, provider=OpenAIProvider(
            base_url=base_url or os.getenv("LOCAL_BASE_URL", "http://localhost:8080/v1"), api_key="local"))
        self.calls = self.prompt_tokens = self.completion_tokens = 0

    def run(self, system, user, output=str, tools=(), deps=None, rounds=0, temperature=0, max_tokens=None, on_step=None):
        settings = {"temperature": temperature, "max_tokens": max_tokens or self.max_tokens}
        if on_step is None:
            result, messages, _ = self.request(system, user, None, output, tools, deps, rounds + 2, settings)
        else:
            result, messages, extra = None, None, ""
            for _ in range(rounds + 2):
                before = steps(messages or [])
                result, messages, done = self.request(system + extra, user, messages, output, tools, deps, 1, settings)
                new = steps(messages)[len(before):]
                if done:
                    break
                text = on_step(new) if new else None
                if text:
                    extra = "\n\n" + text
                    for p in (p for m in messages if isinstance(m, ModelRequest) for p in m.parts):
                        if isinstance(p, SystemPromptPart):
                            p.content = system + extra
        responses = [m for m in messages if isinstance(m, ModelResponse)]
        return Reply(result, transcript(messages), any(m.finish_reason == "length" for m in responses), steps(messages))

    def request(self, system, user, history, output, tools, deps, limit, settings):
        """До limit запросов; -> (ответ или None, все сообщения, закончен ли прогон). Сообщения сохраняются
        и при сбое: траектория и токены не теряются."""
        agent = Agent(self.llm, system_prompt=system, output_type=output, tools=tools, retries=3)
        done = True
        with capture_run_messages() as messages:
            try:
                result = agent.run_sync(None if history else user, message_history=history, deps=deps,
                                        usage_limits=UsageLimits(request_limit=limit), model_settings=settings).output
            except UsageLimitExceeded:
                result, done = None, False
            except UnexpectedModelBehavior:
                result = None
        messages = list(messages)
        responses = [m for m in messages[len(history or []):] if isinstance(m, ModelResponse)]
        self.calls += len(responses)
        self.prompt_tokens += sum(m.usage.input_tokens for m in responses)
        self.completion_tokens += sum(m.usage.output_tokens for m in responses)
        return result, messages, done

    def one(self, system, user, temperature=0, max_tokens=None):
        return self.run(system, user, temperature=temperature, max_tokens=max_tokens)

    def usage(self):
        return dict(calls=self.calls, prompt_tokens=self.prompt_tokens, completion_tokens=self.completion_tokens)


def transcript(messages):
    lines = []
    for m in messages:
        for p in m.parts:
            if isinstance(p, TextPart) and p.content:
                lines.append(p.content)
            elif isinstance(p, ToolCallPart):
                lines.append(f"[call {p.tool_name}] {p.args_as_json_str()}")
            elif isinstance(p, ToolReturnPart):
                lines.append(f"[{p.tool_name}] {p.content}")
    return "\n\n".join(lines)


def steps(messages):
    """Вызовы инструментов: (имя, аргументы, результат); отбивка ModelRetry — результат «Error: ...»."""
    calls, out = {}, []
    for m in messages:
        for p in m.parts:
            if isinstance(p, ToolCallPart):
                calls[p.tool_call_id] = (p.tool_name, p.args_as_json_str())
            elif isinstance(p, ToolReturnPart) and p.tool_call_id in calls:
                out.append((*calls[p.tool_call_id], str(p.content)))
            elif isinstance(p, RetryPromptPart) and p.tool_call_id in calls:
                out.append((*calls[p.tool_call_id], f"Error: {p.content if isinstance(p.content, str) else p.content[0]['msg']}"))
    return out
