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

    def create(self, messages, params):
        r = self.client.chat.completions.create(model=self.name, messages=messages, **params)
        self.calls += 1
        if r.usage:
            self.prompt_tokens += r.usage.prompt_tokens
            self.completion_tokens += r.usage.completion_tokens
        return r.choices[0]

    def ask(self, call):
        choice = self.create(call.messages, call.params)
        reply = text_reply(call, choice.message.content, choice.finish_reason == "length")
        reply.messages = call.messages + [{"role": "assistant", "content": choice.message.content or ""}]
        return reply

    def embed(self, texts, name):
        return [d.embedding for d in self.client.embeddings.create(model=name, input=texts).data]

    def message(self, messages, params):
        """Ответ как есть: (сообщение assistant dict без пустых полей, finish_reason)."""
        choice = self.create(messages, params)
        return choice.message.model_dump(exclude_none=True), choice.finish_reason
