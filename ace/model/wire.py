"""Бэкенд «провод апстрима»: официальный клиент openai, chat.completions.create ровно с messages и params вызова.
Своей логики нет: ни повторов, ни исправления вывода, ни инструментов; ответ текстом разбирает reader вызова."""
from openai import OpenAI

from .. import config
from . import text_reply


class Wire:
    def __init__(self, name, base_url):
        self.name = name
        self.client = OpenAI(base_url=base_url, api_key=config.API_KEY)
        self.calls = self.prompt_tokens = self.completion_tokens = 0

    def ask(self, call):
        r = self.client.chat.completions.create(model=self.name, messages=call.messages, **call.params)
        self.calls += 1
        if r.usage:
            self.prompt_tokens += r.usage.prompt_tokens
            self.completion_tokens += r.usage.completion_tokens
        choice = r.choices[0]
        reply = text_reply(call, choice.message.content, choice.finish_reason == "length")
        reply.messages = call.messages + [{"role": "assistant", "content": choice.message.content or ""}]
        return reply
