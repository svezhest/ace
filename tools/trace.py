"""Снимок поведения методов на фиктивной модели: все запросы, итог и память.
    uv run python tools/trace.py OUT.json [method ...]
Одинаковые промпты -> одинаковые ответы, поэтому два снимка сравнимы (tools/compare.py): так видно, что
правка кода не поменяла запросы там, где не должна."""
import gzip
import hashlib
import json
import sys
import tempfile
import typing
from pathlib import Path

out, names = sys.argv[1], sys.argv[2:]
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pydantic  # noqa: E402
from ace.model import Reply, roles, text_reply  # noqa: E402
from ace.loop import run  # noqa: E402
from ace.learner import swap  # noqa: E402
from ace.methods import METHODS  # noqa: E402
from ace.tasks import TASKS  # noqa: E402

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


def h(*parts):
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
    if origin in (typing.Union, getattr(__import__("types"), "UnionType", None)):
        return fill([a for a in args if a is not type(None)][0], seed)
    if isinstance(tp, type) and issubclass(tp, pydantic.BaseModel):
        return tp(**{k: NAMED.get(k) if k in NAMED and f.annotation is str else fill(f.annotation, seed + i)
                     for i, (k, f) in enumerate(tp.model_fields.items())})
    return None


class Fake:
    """Модель без сети: инструменты не вызывает, ответ — функция от промпта."""
    name = "fake"

    def __init__(self, targets):
        self.targets, self.log = targets, []

    def ask(self, call):
        system, user = roles(call.messages)
        schema, p = call.reader.schema, call.params
        self.log.append(dict(system=system, user=user, output=schema.__name__ if schema else "str",
                             tools=[t.__name__ for t in call.tools], rounds=call.rounds, temperature=p.get("temperature"),
                             max_tokens=p.get("max_tokens"), **({"top_p": p["top_p"]} if "top_p" in p else {})))
        seed = h(system, user, p.get("temperature"), len(self.log) if p.get("temperature") else "")
        if schema is None:
            target = next((t for q, t in self.targets.items() if q in user), None)
            answer = target if target and seed % 3 else "1.00"
            return text_reply(call, BLOB + f"\nFINAL ANSWER: {answer}")
        obj = fill(schema, seed)
        return Reply(obj, json.dumps(obj.model_dump()))

    def usage(self):
        return dict(calls=len(self.log), prompt_tokens=0, completion_tokens=0)


task = TASKS["formula"]
targets = {r["context"]: r["target"] for s in ("", "train", "val") for r in task.load(s)}
# батч 2 и офлайн, чтобы на 4 задачах сработали события батча и прохода
special = {"tfgrpo": (dict(every=2), {}), "mce_fs": (dict(every=2), dict(epochs=2, offline=True)),
           "mce_ace_stand": (dict(every=2), dict(epochs=2, offline=True))}
traces = {}
tmp = Path(tempfile.mkdtemp(prefix="trace-"))
# mce — агенты Claude SDK через LiteLLM (model/claude.py): на фиктивной модели не идёт, его сверка — tests/live/test_mce.py
for name in names or sorted(set(METHODS) - {"mce"}):
    parts, kw = special.get(name, ({}, {}))
    fake = Fake(targets)
    summary = run(task, swap(METHODS[name], **parts) if parts else METHODS[name], fake, 4, str(tmp / name), **kw)
    traces[name] = dict(summary=summary, calls=fake.log, memory=json.load(open(tmp / name / "memory.json")))
    print(name, summary["correct"], len(fake.log), flush=True)
with (gzip.open(out, "wt") if out.endswith(".gz") else open(out, "w")) as f:
    json.dump(traces, f, ensure_ascii=False, indent=1)
