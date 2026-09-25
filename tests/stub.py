"""Модель-заглушка для тестов цикла и уровней: ответ решателя — функция от промпта, ответ по схеме — из словаря
по имени схемы. Запоминает все вызовы."""
import numpy as np

from ace import embed
from ace.loop import Episode, Prompt
from ace.model import Reply, roles, text_reply
from ace.tasks import TASKS

TASK = TASKS["formula"]
TARGETS = {r["question"]: r["target"] for s in ("", "train", "val") for r in TASK.load(s)}


def target_of(user):
    return next(t for q, t in TARGETS.items() if q in user)


class Stub:
    name = "stub"

    def __init__(self, answer=lambda call: "FINAL ANSWER: 0", schemas=None):
        self.answer, self.schemas, self.calls = answer, schemas or {}, []

    def ask(self, c):
        system, user = roles(c.messages)
        output = c.reader.schema or str
        call = dict(system=system, user=user, output=output, tools=c.tools, temperature=c.params.get("temperature"),
                    top_p=c.params.get("top_p"), max_tokens=c.params.get("max_tokens"), deps=c.deps, history=c.history,
                    n=len(self.calls))
        self.calls.append(call)
        if output is str:
            return text_reply(c, self.answer(call))
        obj = self.schemas.get(output.__name__)
        return Reply(obj(call) if callable(obj) else obj, "")

    def message(self, messages, params):
        """Агентный цикл метода (TF-GRPO): ответ без вызовов инструментов."""
        system, user = roles(messages)
        call = dict(system=system, user=user, output=str, tools=params.get("tools"), temperature=params.get("temperature"),
                    top_p=params.get("top_p"), max_tokens=params.get("max_tokens"), deps=None, history=None,
                    n=len(self.calls))
        self.calls.append(call)
        return {"role": "assistant", "content": self.answer(call)}, "stop"

    def embed(self, texts, name):
        """Эмбеддинги — ace.embed (тесты подменяют его таблицей)."""
        return np.asarray(embed.embed(texts)).tolist()

    def usage(self):
        return dict(calls=len(self.calls), prompt_tokens=0, completion_tokens=0)

    def solver_calls(self):
        return [c for c in self.calls if c["system"].startswith(TASK.system)]


def right(call):
    return f"FINAL ANSWER: {target_of(call['user'])}"


def episode(answer="1", ok=None, target="", final=None, shown=(), k=0, question="q"):
    final = final if final is not None else f"FINAL ANSWER: {answer}"
    return Episode(question, k, Prompt(shown=list(shown)), final, final, answer, [], False, [], [], [], ok, target)
