"""Сводка сессии писателя для чтения глазами: python3 probes/1111/ds/sum.py HOME TAG [знаков diff]
Числа, правки с ответом проверки, проигрыш итога, добавленные строки итогового diff, места рассуждения по теме."""
import json
import re
import subprocess
import sys

H, T = sys.argv[1], sys.argv[2]
D = int(sys.argv[3]) if len(sys.argv) > 3 else 2500
L = [json.loads(x) for x in open(f"{H}/logs/{T}.jsonl")]
turns = [x for x in L if x.get("type") == "turn"]
end = [x for x in L if x.get("type") == "end"][-1]
st = end["stats"]
fe = next((x["i"] for x in turns if any(c["name"] == "edit" for c in x["tool_calls"])), None)
bb = sum(1 for x in turns if fe and x["i"] < fe for c in x["tool_calls"] if c["name"] == "bash")
print(f"##### {T}: ходов {st['turns']}, bash {st['bash_calls']}, первая правка на ходу {fe} после {bb} bash, правок "
      f"{st['edits_applied']}/{st['edits_attempted']}, пик {st['max_prompt']}, ген {st['gen_tokens']}, "
      f"мин {round(st['model_sec'] / 60, 1)}, конец: {end['reason']}")
for x in turns:
    for c, r in zip(x["tool_calls"], x["results"]):
        if c["name"] != "edit":
            continue
        try:
            a = json.loads(c["arguments"])
        except Exception:  # noqa: BLE001
            a = {}
        s = r.get("shown") or ""
        k = s.find("python3 tests/rerun.py prints")
        j = s.find("Check against")
        print(f"  ход {x['i']} EDIT {a.get('path') or a.get('file_path') or a.get('file')}: "
              + (s[k + 30:j].strip().replace("\n", " | ")[:330] if k >= 0 else s[:160].replace("\n", " | "))
              + " || " + (s[j + 30:j + 260].strip().replace("\n", " | ") if j >= 0 else ""))
r = subprocess.run(["/Users/user/Projects/nrhsi/nrhsi/bin/python3", "tests/rerun.py"], cwd=f"{H}/work/{T}",
                   capture_output=True, text=True)
print("  ПРОИГРЫШ ИТОГА:", (r.stdout + r.stderr).strip().replace("\n", " | ")[:700])
d = open(f"{H}/out/{T}.diff").read()
if "starting_prompt.md" in d:      # промпт изменён: повтор ничего не сравнивает; проигрываем код с прежним промптом
    import shutil
    import tempfile
    tmp = tempfile.mkdtemp()
    shutil.copytree(f"{H}/work/{T}", f"{tmp}/w", symlinks=True)
    shutil.copy(f"{tmp}/w/tests/orig_src/starting_prompt.md", f"{tmp}/w/src/starting_prompt.md")
    r = subprocess.run(["/Users/user/Projects/nrhsi/nrhsi/bin/python3", "tests/rerun.py"], cwd=f"{tmp}/w",
                       capture_output=True, text=True)
    print("  ПРОИГРЫШ КОДА С ПРЕЖНИМ ПРОМПТОМ:", (r.stdout + r.stderr).strip().replace("\n", " | ")[:700])
    shutil.rmtree(tmp)
files = re.findall(r"^\+\+\+ b/(\S+)", d, re.M)
add = [x for x in d.splitlines() if x.startswith(("+", "-")) and not x.startswith(("+++", "---"))]
print("  ФАЙЛЫ:", files, "| строк +/-:", sum(x[0] == "+" for x in add), sum(x[0] == "-" for x in add))
print("  DIFF:\n    " + "\n    ".join(x[:230] for x in add)[:D])
kw = re.compile(r"legit|passed|passing|token|state chang|false positive|run[ _]?8\b|run[ _]?20\b|observation (is|says|claims|"
                r"suggests|asks)|already compares|only the code|not accurate|inaccurate|wrong about|disagree|however, the "
                r"observation|but the observation|misdiagnos|incorrect", re.I)
hits = []
for x in turns:
    for src in (x.get("reasoning") or "", x.get("content") or ""):
        for s in re.split(r"(?<=[.!?])\s+|\n+", src):
            if kw.search(s) and len(s) > 40:
                hits.append(f"[{x['i']}] {s.strip()[:260]}")
print(f"  ПО ТЕМЕ ({len(hits)} мест), первые:")
for h in hits[:9]:
    print("    •", h)
fin = [x for x in turns if (x.get("content") or "").strip()]
if fin:
    print("  ПОСЛЕДНИЙ ТЕКСТ:", fin[-1]["content"][:500].replace("\n", " ⏎ "))
