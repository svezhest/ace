"""Клиент к OpenAI-совместимому gateway. Считает вызовы и токены."""
import os
from dataclasses import dataclass

from openai import OpenAI


@dataclass
class Reply:
    text: str
    tokens: int
    truncated: bool


class Model:
    def __init__(self, name=None, max_tokens=4096, base_url=None):
        self.name = name or os.getenv("MODEL", "ornith15-9b")
        self.max_tokens = max_tokens
        self.client = OpenAI(base_url=base_url or os.getenv("LOCAL_BASE_URL", "http://localhost:8080/v1"),
                             api_key="local", timeout=3600, max_retries=8)
        self.calls = self.prompt_tokens = self.completion_tokens = 0

    def chat(self, system, user, temperature=0, n=1, json=False):
        """-> list[Reply] длины n."""
        r = self.client.chat.completions.create(
            model=self.name, temperature=temperature, n=n, max_tokens=self.max_tokens,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            **({"response_format": {"type": "json_object"}} if json else {}))
        self.calls += 1
        self.prompt_tokens += r.usage.prompt_tokens
        self.completion_tokens += r.usage.completion_tokens
        per = r.usage.completion_tokens // max(n, 1)
        return [Reply(c.message.content or "", per, c.finish_reason == "length") for c in r.choices]

    def one(self, system, user, **kw):
        return self.chat(system, user, **kw)[0]

    def usage(self):
        return dict(calls=self.calls, prompt_tokens=self.prompt_tokens, completion_tokens=self.completion_tokens)
