"""Механика правок редактора: цел ли харнесс в work/<tag>/src.

python check.py TAG [TAG ...]   -> out/<tag>.check.json и строка на тег
1) py_compile всех .py в src; 2) import harness в venv бенчмарка (src копии первым в sys.path);
3) тесты бенчмарка на заглушке модели (tests/test_<bench>.py — копии с SRC из окружения): по каждому тесту pass/fail.
Тесты «стартовое состояние» (hooks.py пуст, промпт = апстрим, повтор апстрима) падают по построению при правке
этих файлов — они отмечены как expected_if_changed, а не как поломка.
"""
import glob
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BENCH = {"alf": os.path.expanduser("~/Projects/nrhsi/alfworld"), "app": os.path.expanduser("~/Projects/nrhsi/appworld")}
TESTS_TIMEOUT = 600  # с; тесты бенчмарка на заглушке идут ~25 с (ALF), ~50 с (App)
START_STATE = {"test_hooks_file_is_empty", "test_start_state", "test_replay_equals_upstream_requests"}


def check(tag):
    summ = json.load(open(f"{HERE}/out/{tag}.summary.json"))
    b = summ["bench"]
    src = f"{HERE}/work/{tag}/src"
    res = {"tag": tag, "bench": b}
    errs = []
    for p in glob.glob(f"{src}/**/*.py", recursive=True):
        try:
            compile(open(p, encoding="utf-8").read(), p, "exec")
        except SyntaxError as e:
            errs.append(f"{os.path.relpath(p, src)}: {e.msg} (line {e.lineno})")
    res["compile_errors"] = errs
    py = f"{BENCH[b]}/.venv/bin/python"
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    r = subprocess.run([py, "-c", "import sys; sys.path[:0]=[sys.argv[1], sys.argv[2]]; import harness, hooks; "
                        "print('ok')", src, f"{BENCH[b]}/runner"], capture_output=True, text=True, env=env,
                       cwd=BENCH[b])
    res["import_ok"] = r.stdout.strip() == "ok"
    if not res["import_ok"]:
        res["import_error"] = r.stderr[-800:]
    env.update(BENCH_ROOT=BENCH[b], EDITOR_SRC=src)
    if b == "alf":
        env.setdefault("ALFWORLD_DATA", f"{BENCH[b]}/data/alfworld")
    try:
        r = subprocess.run([py, "-m", "pytest", "-q", "-rA", "-p", "no:cacheprovider", f"{HERE}/tests/test_{b}.py"],
                           capture_output=True, text=True, env=env, cwd=BENCH[b], timeout=TESTS_TIMEOUT)
    except subprocess.TimeoutExpired as e:   # правка подвесила тест (бесконечный цикл): это результат проверки
        out = e.stdout.decode() if isinstance(e.stdout, bytes) else (e.stdout or "")
        r = subprocess.CompletedProcess(e.cmd, -1, out, "")
        res["tests_timeout"] = TESTS_TIMEOUT
    tests = {}
    for m in re.finditer(r"^(PASSED|FAILED|ERROR|SKIPPED)\s+\S*::(\w+)(\[[^\]]*\])?", r.stdout, re.M):
        tests[m.group(2) + (m.group(3) or "")] = m.group(1)
    res["tests"] = tests
    bad = {k: v for k, v in tests.items() if v in ("FAILED", "ERROR") and k.split("[")[0] not in START_STATE}
    res["tests_failed"] = sorted(bad)
    res["tests_failed_start_state"] = sorted(k for k, v in tests.items() if v in ("FAILED", "ERROR")
                                             and k.split("[")[0] in START_STATE)
    if bad or res.get("tests_timeout"):
        res["pytest_tail"] = r.stdout[-6000:]
    orig = f"{BENCH[b]}/view/src/starting_prompt.md"
    if b == "app" and os.path.exists(f"{src}/starting_prompt.md"):
        slots = lambda t: set(re.findall(r"\{\{\s*([\w.]+)\s*\}\}", t))      # noqa: E731
        roles = lambda t: re.findall(r"^(USER|ASSISTANT|SYSTEM):$", t, re.M)  # noqa: E731
        a, e = open(orig).read(), open(f"{src}/starting_prompt.md").read()
        res["prompt_slots_missing"] = sorted(slots(a) - slots(e))
        res["prompt_roles"] = f"{len(roles(a))}->{len(roles(e))}"
    for p in glob.glob(f"{src}/**/__pycache__", recursive=True):
        subprocess.run(["rm", "-rf", p])
    json.dump(res, open(f"{HERE}/out/{tag}.check.json", "w"), ensure_ascii=False, indent=1)
    return res


if __name__ == "__main__":
    for t in sys.argv[1:]:
        r = check(t)
        print(json.dumps({k: r.get(k) for k in ("tag", "compile_errors", "import_ok", "tests_failed", "tests_timeout",
                                             "tests_failed_start_state", "prompt_slots_missing", "prompt_roles")
                          if k in r}, ensure_ascii=False))
        print("  tests:", len(r["tests"]), "pass", sum(v == "PASSED" for v in r["tests"].values()))
