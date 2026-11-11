"""6.11, автор: вид без комментариев и докстрингов в src/*.py и с минимальным README (структура и формат логов).
python3 -m nrhsi.plain ВИД ВЫХОД -> ВЫХОД/{README.md, src/, logs/} и ВЫХОД.linemap.json {файл: {старая строка: новая}}.
Поведение кода то же: ast без докстрингов совпадает."""
import ast
import io
import json
import os
import re
import shutil
import sys
import tokenize

README = {
"app": """# AppWorld agent harness

- `src/` — the harness of the agent: the prompt and the code that run it on a task. This is what you edit.
  - `harness.py` — the agent loop; `hooks.py` — functions that `harness.py` calls; `hook_types.py` — what each of them is given and may return.
  - `starting_prompt.md` — the prompt. `{{ ... }}` in it are slots that the benchmark fills with the task's values; the slot names are fixed.
  - `bridge.py` — connection to the benchmark. Not part of the harness: do not edit.
- `logs/` — runs of the harness in `src/` as it was at the start.
  - `run_N.jsonl` — one episode as a stream of events, one per line. `event` says who produced it: `bridge` — a call to the benchmark (`fill`: the values put into the prompt's slots; `execute`: code run by the benchmark, `step` — its number; `end`: how the benchmark ended the episode — `finished`, `step limit`, `error`; `error` with `detail: "repeated reply"` is the bridge's own stop: the model sent the same reply three times in a row); `prompt` — a message the harness built from `src/starting_prompt.md`; `env` — a message with the benchmark's output, as the model received it; `model` — the model's reply; `harness` — other messages from the harness (`from`: its file in `src/`). The `message` fields in order are the conversation as the model saw it.
  - `results.jsonl` — one line per run: `{run, ok, reason}`.
  - Read the failed runs; the passed runs are there for comparison and grep.
""",
"alf": """# ALFWorld agent harness

- `src/` — the harness of the agent: the prompts and the code that run it on a task. This is what you edit.
  - `harness.py` — the agent loop; `hooks.py` — functions that `harness.py` calls; `hook_types.py` — what each of them is given and may return.
  - `*.md` — prompts; `starting_prompt.md` is the system prompt.
  - `bridge.py` — connection to the benchmark. Not part of the harness: do not edit.
- `logs/` — runs of the harness in `src/` as it was at the start.
  - `run_N.jsonl` — one episode as a stream of events, one per line. `event` says who produced it: `bridge` — a call through the bridge (`start`; `send`: a model reply handed to the task, `turn` — its number, `not_shown` — the task's messages the harness did not put into the conversation; `end`: how the task ended the episode — `finished`, `step limit`, `error` with `detail`; `detail: "repeated reply"` is the bridge's own stop: the model sent the same reply three times in a row); `prompt` — the system message built from `src/starting_prompt.md`; `env` — a message of the task, as the model received it; `model` — the model's reply; `harness` — other messages from the harness (`from`: its file in `src/`). The `message` fields in order are the conversation as the model saw it.
  - `results.jsonl` — one line per run: `{run, ok, reason}`.
  - Read the failed runs; the passed runs are there for comparison and grep.
""",
}


def _doc_lines(tree):
    """Строки докстрингов модуля, классов и функций."""
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and n.body:
            d = n.body[0]
            if isinstance(d, ast.Expr) and isinstance(d.value, ast.Constant) and isinstance(d.value.value, str):
                out.update(range(d.lineno, d.end_lineno + 1))
    return out


def _nodoc(tree):
    for n in ast.walk(tree):
        if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and n.body:
            d = n.body[0]
            if isinstance(d, ast.Expr) and isinstance(d.value, ast.Constant) and isinstance(d.value.value, str):
                n.body = n.body[1:] or [ast.Pass()]
    return ast.dump(tree)


def strip(src):
    """-> (текст без комментариев и докстрингов, {старая строка: новая})."""
    lines = src.split("\n")
    drop = _doc_lines(ast.parse(src))
    cut = {}                                   # строка -> столбец начала комментария
    for t in tokenize.generate_tokens(io.StringIO(src).readline):
        if t.type == tokenize.COMMENT:
            cut[t.start[0]] = t.start[1]
    for n in ast.walk(ast.parse(src)):          # докстринг должен занимать свои строки целиком
        if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and n.body:
            d = n.body[0]
            if isinstance(d, ast.Expr) and isinstance(d.value, ast.Constant) and isinstance(d.value.value, str):
                first = lines[d.lineno - 1]
                assert d.col_offset == len(first) - len(first.lstrip()), d.lineno
                assert d.end_col_offset == len(lines[d.end_lineno - 1].rstrip().encode()), d.end_lineno   # смещения ast — в байтах
    new, lmap = [], {}
    for i, ln in enumerate(lines, 1):
        if i in drop:
            continue
        if i in cut:
            ln = ln[:cut[i]].rstrip()
            if not ln.strip():
                continue
        lmap[i] = len(new) + 1
        new.append(ln)
    text = "\n".join(new)
    text = re.sub(r"\n{4,}", "\n\n\n", text)            # не больше двух пустых подряд
    text = re.sub(r"^\n+", "", text)
    # тело, оставшееся пустым после докстринга
    tree = None
    while True:
        try:
            tree = ast.parse(text)
            break
        except SyntaxError as e:
            assert "expected an indented block" in str(e), e
            tl = text.split("\n")
            prev = tl[e.lineno - 2]
            ind = len(prev) - len(prev.lstrip()) + 4
            tl.insert(e.lineno - 1, " " * ind + "pass")
            text = "\n".join(tl)
    assert _nodoc(ast.parse(src)) == _nodoc(tree), "поведение изменилось"
    # пересчёт карты после схлопывания пустых строк: по совпадению непустых строк по порядку
    out = text.split("\n")
    j, fixed = 0, {}
    for i in sorted(lmap):
        s = new[lmap[i] - 1]
        if not s.strip():
            continue
        while out[j] != s:
            j += 1
        fixed[i] = j + 1
        j += 1
    return text, fixed


def strip_dir(src):
    """Все .py в src/ — без комментариев и докстрингов, на месте (дерево: каждый узел). Файл, который не удалось
    разобрать или у которого поменялось бы поведение, остаётся как есть -> список таких."""
    left = []
    for p in sorted(os.listdir(src)):
        if p.endswith(".py"):
            f = os.path.join(src, p)
            try:
                t, _ = strip(open(f).read())
            except (AssertionError, SyntaxError, tokenize.TokenError, IndexError) as e:
                left.append(f"{p}: {type(e).__name__} {e}")
                continue
            open(f, "w").write(t)
    return left


def main():
    view, dst = sys.argv[1], sys.argv[2]
    bench = "alf" if "alf" in open(f"{view}/README.md").readline().lower() else "app"
    if os.path.exists(dst):
        shutil.rmtree(dst)
    os.makedirs(dst)
    shutil.copytree(f"{view}/src", f"{dst}/src", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(f"{view}/logs", f"{dst}/logs")
    with open(f"{dst}/README.md", "w") as f:
        f.write(README[bench])
    maps = {}
    for p in sorted(os.listdir(f"{dst}/src")):
        if p.endswith(".py"):
            t, m = strip(open(f"{dst}/src/{p}").read())
            open(f"{dst}/src/{p}", "w").write(t)
            maps[f"src/{p}"] = m
    json.dump({"view": view, "bench": bench, "map": maps}, open(f"{dst}.linemap.json", "w"), indent=0)
    print(dst, {k: f"{max(v)} -> {max(v.values())}" for k, v in maps.items()})


if __name__ == "__main__":
    main()
