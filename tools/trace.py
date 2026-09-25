"""Трасса промптов методов на фиктивной модели:
    uv run python tools/trace.py [--root DIR] OUT.json [method ...]
DIR — каталог, где лежит пакет ace (по умолчанию корень репозитория; для эталона — worktree тега).
Одинаковые промпты -> одинаковые ответы, поэтому трассы сравнимы (tools/compare.py)."""
import gzip
import hashlib
import json
import sys
import tempfile
import typing
from pathlib import Path

args = sys.argv[1:]
root = Path(__file__).resolve().parent.parent
if args and args[0] == "--root":
    root, args = Path(args[1]).resolve(), args[2:]
out, names = args[0], args[1:]
sys.path.insert(0, str(root))
import pydantic  # noqa: E402
from ace import model as M  # noqa: E402
from ace.loop import run  # noqa: E402
try:
    from ace.learner import swap  # noqa: E402
except ImportError:             # старый код (эталон с тега)
    from ace.loop import swap  # noqa: E402
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
        return tp(**{k: NAMED.get(k) if k in NAMED and str in (f.annotation, *typing.get_args(f.annotation))
                     else fill(f.annotation, seed + i)
                     for i, (k, f) in enumerate(tp.model_fields.items())})
    return None


class Fake:
    """Модель без сети: инструменты не вызывает, ответ — функция от промпта."""
    name, max_tokens = "fake", 4096

    def __init__(self, targets):
        self.targets, self.log = targets, []

    def run(self, system, user, output=str, tools=(), deps=None, rounds=0, temperature=0, max_tokens=None, on_step=None,
            top_p=None):
        self.log.append(dict(system=system, user=user, output=getattr(output, "__name__", str(output)),
                             tools=[t.__name__ for t in tools], rounds=rounds, temperature=temperature, max_tokens=max_tokens,
                             **({"top_p": top_p} if top_p is not None else {})))
        seed = h(system, user, temperature, len(self.log) if temperature else "")
        if output is str:
            target = next((t for q, t in self.targets.items() if q in user), None)
            answer = target if target and seed % 3 else "1.00"
            text = BLOB + f"\nFINAL ANSWER: {answer}"
            return M.Reply(text, text, False, [])
        obj = fill(output, seed)
        return M.Reply(obj, json.dumps(obj.model_dump()), False, [])

    def one(self, system, user, temperature=0, max_tokens=None):
        return self.run(system, user, temperature=temperature, max_tokens=max_tokens)

    def usage(self):
        return dict(calls=len(self.log), prompt_tokens=0, completion_tokens=0)


task = TASKS["formula"]
targets = {r["context"]: r["target"] for s in ("", "train", "val") for r in task.load(s)}
# батч 2 и офлайн, чтобы на 4 задачах сработали события батча и прохода
special = {"tfgrpo": (dict(every=2), {}), "mce": (dict(every=2), dict(epochs=2, offline=True)),
           "mce_ace": (dict(every=2), dict(epochs=2, offline=True))}
traces = {}
tmp = Path(tempfile.mkdtemp(prefix="trace-"))
for name in names or sorted(METHODS):
    parts, kw = special.get(name, ({}, {}))
    fake = Fake(targets)
    summary = run(task, swap(METHODS[name], **parts) if parts else METHODS[name], fake, 4, str(tmp / name), **kw)
    traces[name] = dict(summary=summary, calls=fake.log, memory=json.load(open(tmp / name / "memory.json")))
    print(name, summary["correct"], len(fake.log), flush=True)
with (gzip.open(out, "wt") if out.endswith(".gz") else open(out, "w")) as f:
    json.dump(traces, f, ensure_ascii=False, indent=1)
