# P4 — комбинатор на 9B (`--arm merge`)

[Указатель проб](../INDEX.md) · хронология: [3.11](../days/1103.md) · как устроено — [README](../README.md)

<!-- LAB-1103.md:312–320 -->
### P4. Комбинатор на 9B (`--arm merge`, 67a0bf0, 3d9cf44)
- **Вопрос.** Сводит ли агент две ветки в один рабочий харнесс лучше, чем механическое слияние?
- **База.** `editor/merge3.py` — git merge-file по файлам src/ от общего предка; при конфликте берётся версия a.
- **Вход агента.** Вид `merge3 --markers`: файлы с маркерами конфликта git, в первом сообщении — diff a и b против общего предка и список файлов с конфликтом. Цель: «Keep what each version adds: resolve every conflict, and where a and b do the same thing in different ways or get in each other's way, keep one way that works.»
- **Пилот.** App: a = n8, b = n12, предок n4. Без конфликта слились harness.py и hooks.py; конфликт один — `starting_prompt.md`, строки 92–101: 5.3 и 12.3 правят один пример. Smoke механического слияния проходит.
- **Задания.** `mg_app_n8+n12_s{1,2}` (сессии); `valapp_merge_n8+n12` (механическое) и `valapp_mg_n8+n12_s1` (агент) — App val, 57 задач, пары с n8, n0 и с n0_r2.
- **Мерка.** Процесс: разрешены ли все маркеры, проходит ли smoke, что сделано с дублем 5.3/12.3. Эффект — пары на val.
- **Ожидание.** Маркеры разрешены в обеих сессиях. На val оба слияния ≈ n8 в пределах P0: полезные правки App (4.3a, 4.3b, 5.3) уже на одной ветке. Пилот проверяет механику, а не прирост.

*Из записи «7. P4 и P6 — ручной разбор, 06:00» (LAB-1103.md; заголовок и остальное — в [P6](P6-smoke-calls.md)):*

<!-- LAB-1103.md:435–436 -->
- **P4:** комбинатор s2 верен, s1 выкинул механизм версии a и потерял текст D.

*Из записи «8. Val App и P5, 13:00» (LAB-1103.md; заголовок и остальное — в [P5](P5-reviewer-check.md)):*

<!-- LAB-1103.md:439 -->
- **Ошибка.** Слияние (`valapp_mg_n8+n12_s1`) поставлено на val, хотя комбинатор не откалиброван. Мерить его на val нечего: проверка комбинатора — ручное чтение diff (§7 уже сделано). Остановлено на 28/57, задание удалено. Так же не стоило мерить на val и 3-way merge.

## Код

<!-- LAB-1103.md:321–391 -->
**Код пробы** (приписано 10.11). Из кода убран в a13b543: в develop осталась одна база. Последний коммит с этим кодом — 951bc3b (`git show 951bc3b:ФАЙЛ`); номера строк в листинге — по нему.

`--arm merge` (P4)

```python
# nrhsi/editor/prompt.py:28-32
"merge": ("Two versions of this harness, a and b, were made independently from the same original version, each to "
          "make the agent fail fewer tasks. src/ here is the two merged line by line; their changes against the "
          "original, and the files where both changed the same lines, are in the first message.",
          "Keep what each version adds: resolve every conflict, and where a and b do the same thing in different "
          "ways or get in each other's way, keep one way that works."),

# nrhsi/editor/inputs.py:173-176
def src_diff(x, y):
    """diff -ruN src/ двух узлов, пути — src/FILE."""
    r = subprocess.run(["diff", "-ruN", "-x", "__pycache__", f"{x}/src", f"{y}/src"], capture_output=True, text=True)
    return r.stdout.replace(f"{x}/src/", "src/").replace(f"{y}/src/", "src/")

# nrhsi/editor/inputs.py:179-187
def first_user_merge(view):
    """--arm merge (3.11): изменения a и b против общего предка и файлы с конфликтом — по merge.json вида (editor/merge3.py)."""
    m = json.load(open(f"{view}/merge.json"))
    conf = [f"src/{f}" for f, s in m["files"].items() if s.startswith("conflict")]
    parts = [f"## Changes in {k} against the original\n```diff\n{src_diff(m['base'], m[k]).rstrip()}\n```" for k in ("a", "b")]
    tail = ("Files where a and b changed the same lines, with git conflict markers (<<<<<<< a, =======, >>>>>>> b): "
            + ", ".join(conf) + "." if conf else "No file has conflicts: a and b changed different lines.")
    return ("\n\n".join(parts) + "\n\n" + tail + "\n\nMake src/ one working harness with what each version adds. "
            "Call finish when you are done.")

# editor/merge3.py:1-38
"""Слияние двух узлов от общего предка без модели: 3-way merge src/ по файлам (git merge-file).

  python3 editor/merge3.py BASE A B OUT [--markers]

OUT — вид (README.md из A, src/). Файл без конфликта — слитый; с конфликтом — версия A (база сравнения),
с --markers — с маркерами конфликта git (<<<<<<< a / ======= / >>>>>>> b): вход комбинатора (editor --arm merge).
Итог — OUT/merge.json: base, a, b, по файлу: clean | a-only | b-only | conflict (число конфликтов).
"""
import json
import os
import shutil
import subprocess
import sys

base, a, b, out = sys.argv[1:5]
markers = "--markers" in sys.argv[5:]
if os.path.exists(out):
    shutil.rmtree(out)
os.makedirs(f"{out}/src")
shutil.copy(f"{a}/README.md", out)
files = sorted((set(os.listdir(f"{a}/src")) | set(os.listdir(f"{b}/src"))) - {"__pycache__"})
res = {}
for f in files:
    pa, pb, po = f"{a}/src/{f}", f"{b}/src/{f}", f"{base}/src/{f}"
    if not os.path.exists(pb) or not os.path.exists(pa):     # файл есть только в одной ветке
        shutil.copy(pa if os.path.exists(pa) else pb, f"{out}/src/{f}")
        res[f] = "a-only" if os.path.exists(pa) else "b-only"
        continue
    o = po if os.path.exists(po) else os.devnull
    p = subprocess.run(["git", "merge-file", "-p", "-L", "a", "-L", "original", "-L", "b", pa, o, pb], capture_output=True)
    if p.returncode == 0 or markers:
        open(f"{out}/src/{f}", "wb").write(p.stdout)
        res[f] = "clean" if p.returncode == 0 else f"conflict ({p.returncode})"
    else:
        shutil.copy(pa, f"{out}/src/{f}")    # без --markers: при конфликте — версия a
        res[f] = f"conflict ({p.returncode})"
json.dump({"base": base, "a": a, "b": b, "files": res}, open(f"{out}/merge.json", "w"), indent=1)
print(json.dumps(res))
```


## Связанные записи

- [§1 Val](VAL1-tree-node-val.md): строка «Val App dev (57), T=0»: merge n8+n12 на val
- [3.11](../days/1103.md): «Ошибки дня, отмеченные автором» (§10)
- [5.11](../days/1105.md): «Пробы с исходом по построению»: 3-way merge n8+n12 на val
