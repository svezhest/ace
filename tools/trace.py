"""Снимок поведения методов на фиктивной модели: все запросы, итог и память.
    uv run python -m tools.trace OUT.json [method ...]
Одинаковые промпты -> одинаковые ответы, поэтому два снимка сравнимы (tools/compare.py): так видно, что
правка кода не поменяла запросы там, где не должна."""
import gzip
import hashlib
import json
import sys
import tempfile
import types
import typing
from pathlib import Path

import pydantic

from ace.model import Call, Reply, roles, text_reply
from ace.loop import Protocol, run
from ace.learner import swap
from ace.methods import METHODS
from ace.tasks import TASKS

BLOB = """Reasoning about the task.
<subtask>
<description>Compute the ratio of two given values.</description>
<solution>Divide.</solution>
<result>0.5</result>
</subtask>
<cheatsheet>
Version 1. Always divide carefully and round to two decimals. Keep units consistent across all steps of the solution.
</cheatsheet>
<insight>If the question gives a percentage, then convert it to a decimal first.</insight>
```insights
If the question gives a percentage, then convert it to a decimal first and check units.
```
<Experiences>
1. Unit check: Convert percentages to decimals before using them in formulas.
</Experiences>
```json
[{"operation": "ADD", "id": null, "content": "Rounding: Round only the final answer."}]
```
```judgment
Solution 2 is better.
```
[r1] helpful=2 harmful=0 :: merged bullet text
VERDICT: correct
USED: r1, r2"""


def stable_hash(*parts):
    """Число из частей, одно и то же от запуска к запуску (hash() строк случаен)."""
    return int(hashlib.md5("|".join(map(str, parts)).encode()).hexdigest(), 16)


NAMED = dict(scope="strategic", tag="helpful", type="ADD", section="formulas_and_calculations", confidence="high",
             domain="general", id="r1", op="add", kind="insight")


def fill(tp, seed):
    origin, args = typing.get_origin(tp), typing.get_args(tp)
    if tp is str:
        return f"text {seed % 997}"
    if tp is float:
        return 0.9
    if tp is int:
        return seed % 2
    if tp is bool:
        return False
    if origin is typing.Literal:
        return args[0]
    if origin in (list, typing.List):
        return [fill(args[0], seed + 1)] if args else []
    if origin in (typing.Union, types.UnionType):
        return fill([a for a in args if a is not type(None)][0], seed)
    if isinstance(tp, type) and issubclass(tp, pydantic.BaseModel):
        values = {}
        for i, (name, f) in enumerate(tp.model_fields.items()):
            if name in NAMED and f.annotation is str:
                values[name] = NAMED[name]
            else:
                values[name] = fill(f.annotation, seed + i)
        return tp(**values)
    return None


class Fake:
    """Модель без сети: инструменты не вызывает, ответ — функция от промпта."""
    name = "fake"
    on_wire = True          # агентный цикл TF-GRPO — через message, как на проводе

    def __init__(self, targets):
        self.targets = targets
        self.log = []

    def ask(self, call):
        system, user = roles(call.messages)
        schema, params = call.reader.schema, call.params
        entry = dict(system=system, user=user, output=schema.__name__ if schema else "str",
                     tools=[t.__name__ for t in call.tools], rounds=call.rounds, temperature=params.get("temperature"),
                     max_tokens=params.get("max_tokens"))
        if "top_p" in params:
            entry["top_p"] = params["top_p"]
        self.log.append(entry)
        # при T > 0 ответ зависит и от номера вызова: повтор того же запроса — другой ответ
        seed = stable_hash(system, user, params.get("temperature"), len(self.log) if params.get("temperature") else "")
        if schema is None:
            target = next((t for q, t in self.targets.items() if q in user), None)
            answer = target if target and seed % 3 else "1.00"
            return text_reply(call, BLOB + f"\nFINAL ANSWER: {answer}")
        obj = fill(schema, seed)
        return Reply(obj, json.dumps(obj.model_dump()))

    def message(self, messages, params):
        """Агентный цикл метода (TF-GRPO): ответ без вызовов инструментов."""
        reply = self.ask(Call(messages, {k: v for k, v in params.items() if k != "tools"}))
        return {"role": "assistant", "content": reply.output}, "stop"

    def embed(self, texts, name):
        """Векторы без модели: по хешу текста."""
        return [[(stable_hash(t) % 97 + 1) / 97, 1.0] for t in texts]

    def usage(self):
        return dict(calls=len(self.log), prompt_tokens=0, completion_tokens=0)


# батч 2 и офлайн, чтобы на 4 вопросах сработали события батча и прохода
SPECIAL = {"tfgrpo": dict(every=2), "mce_fs": dict(every=2, protocol=Protocol(offline=True, epochs=2)),
           "mce_ace_stand": dict(every=2, protocol=Protocol(offline=True, epochs=2))}


def main():
    out, names = sys.argv[1], sys.argv[2:]
    task = TASKS["formula"]
    targets = {r["question"]: r["target"] for s in ("", "train", "val") for r in task.load(s)}
    traces = {}
    tmp = Path(tempfile.mkdtemp(prefix="trace-"))
    # mce — агенты Claude SDK через LiteLLM (model/claude.py): на фиктивной модели не идёт, его сверка —
    # tests/live/test_mce.py
    for name in names or sorted(set(METHODS) - {"mce"}):
        levels = SPECIAL.get(name, {})
        learner = swap(METHODS[name], **levels) if levels else METHODS[name]
        fake = Fake(targets)
        summary = run(task, learner, fake, 4, str(tmp / name))
        traces[name] = dict(summary=summary, calls=fake.log, memory=json.load(open(tmp / name / "memory.json")))
        print(name, summary["correct"], len(fake.log), "errors", summary["errors"], flush=True)
    with (gzip.open(out, "wt") if out.endswith(".gz") else open(out, "w")) as f:
        json.dump(traces, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
