"""Модель-заглушка для тестов цикла и уровней: ответ решателя — функция от промпта, ответ по схеме — из словаря
по имени схемы. Запоминает все вызовы."""
from ace.loop import Episode, Prompt
from ace.model import Reply
from ace.tasks import TASKS

TASK = TASKS["formula"]
TARGETS = {r["context"]: r["target"] for s in ("", "train", "val") for r in TASK.load(s)}


def target_of(user):
    return next(t for q, t in TARGETS.items() if q in user)


class Stub:
    name, max_tokens = "stub", 100

    def __init__(self, answer=lambda call: "FINAL ANSWER: 0", schemas=None):
        self.answer, self.schemas, self.calls = answer, schemas or {}, []

    def run(self, system, user, output=str, tools=(), deps=None, rounds=0, temperature=0, max_tokens=None, on_step=None):
        call = dict(system=system, user=user, output=output, tools=tools, temperature=temperature, n=len(self.calls))
        self.calls.append(call)
        if output is str:
            text = self.answer(call)
            return Reply(text, text, False, [])
        obj = self.schemas.get(output.__name__)
        obj = obj(call) if callable(obj) else obj
        return Reply(obj, "", False, [])

    def one(self, system, user, temperature=0, max_tokens=None):
        return self.run(system, user, temperature=temperature, max_tokens=max_tokens)

    def usage(self):
        return dict(calls=len(self.calls), prompt_tokens=0, completion_tokens=0)

    def solver_calls(self):
        return [c for c in self.calls if c["system"].startswith(TASK.system)]


def right(call):
    return f"FINAL ANSWER: {target_of(call['user'])}"


def episode(answer="1", ok=None, target="", final=None, shown=(), k=0, question="q"):
    final = final if final is not None else f"FINAL ANSWER: {answer}"
    return Episode(question, k, Prompt(shown=list(shown)), final, final, answer, [], False, [], [], [], ok, target)
