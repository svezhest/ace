"""Модель через pydantic-ai: один агент на вызов, tools и схема ответа передаются явно."""
import os
os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")
from dataclasses import dataclass

from pydantic_ai import Agent, UsageLimits
from pydantic_ai.exceptions import UnexpectedModelBehavior, UsageLimitExceeded
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart, ToolReturnPart
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

    def run(self, system, user, output=str, tools=(), deps=None, rounds=0, temperature=0):
        agent = Agent(self.llm, system_prompt=system, output_type=output, tools=tools, retries=1)
        try:
            messages = agent.run_sync(user, deps=deps, usage_limits=UsageLimits(request_limit=rounds + 2),
                                      model_settings={"temperature": temperature, "max_tokens": self.max_tokens})
            result, messages = messages.output, messages.new_messages()
        except (UsageLimitExceeded, UnexpectedModelBehavior) as e:
            result, messages = None, getattr(e, "messages", []) or []
        responses = [m for m in messages if isinstance(m, ModelResponse)]
        self.calls += len(responses)
        self.prompt_tokens += sum(m.usage.input_tokens for m in responses)
        self.completion_tokens += sum(m.usage.output_tokens for m in responses)
        return Reply(result, transcript(messages), any(m.finish_reason == "length" for m in responses), steps(messages))

    def one(self, system, user, temperature=0):
        return self.run(system, user, temperature=temperature)

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
    calls, out = {}, []
    for m in messages:
        for p in m.parts:
            if isinstance(p, ToolCallPart):
                calls[p.tool_call_id] = (p.tool_name, p.args_as_json_str())
            elif isinstance(p, ToolReturnPart) and p.tool_call_id in calls:
                out.append((*calls[p.tool_call_id], str(p.content)))
    return out
