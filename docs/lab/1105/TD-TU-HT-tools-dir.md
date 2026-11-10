# TD, TU, HT — каталог инструментов (`--tools-dir`, `--hide-tools`)

[Указатель проб](../INDEX.md) · хронология: [5.11](../days/1105.md) · как устроено — [README](../README.md)

<!-- LAB-1103.md:953–957 -->
### Проба: каталог инструментов (5.11, пользователь: «спрятать в tools, или даже __tools, спрятать насовсем»)
- Наблюдение: исходники tests/ читают 191 сессия из 225, медиана — 8-й bash; перед этим «check the test files», «the tests to understand the constraints». Гипотеза: каталог `tests/` модель читает как спецификацию (привычка задач на код); `tests/rerun.py` — обёртка с `import rerun_core`, по которому она идёт дальше.
- Коммит: `--tools-dir NAME` (всё, что видит писатель, — `NAME/` вместо `tests/`), `--hide-tools` (в копии нет каталога инструментов; `rerun [N] [--at K]` и `smoke` — команды, исполняются харнессом в песочнице с правом чтения каталога вне копии, допустим хвост `| head/tail/grep/wc/nl/sed`). Без флагов промпт байт в байт прежний (сверено --dry). Заглушка: все 4 режима, команды писателя и проверки харнесса.
- Сессии: W1 (`--rerun`), seed 1, 10 наблюдений × {TD = tools, TU = __tools, HT = hide}; база — W1. Мерка: доля сессий, читающих исходники инструментов; на каком bash первая правка; вердикт.

*Из записи «Чтение очереди писателя, часть 1 (05.11)» (LAB-1103.md; заголовок и остальное — в [5.11](../days/1105.md)):*

<!-- LAB-1103.md:1063–1068 -->
- Каталог инструментов, механика (W1 seed 1, по 10 сессий):
  - Сессий, читавших исходник rerun/smoke: W1 9, TD 9 → 8, TU 9, HT 0.
  - Средний bash до первой правки: W1 22.2, TD 24.7, TU 21.4, HT 21.3.
  - HT: 7 из 10 искали инструменты (which/find/ls). Сами вызвали rerun 1 раз, smoke 2 раза на 10 сессий.
  - Бюджет у HT уходит в src и logs. Вердикты ещё не читал.

*Из записи «Чтение очереди писателя, часть 2 (05.11) — таблицы в runs/wvar_1104/READ.md» (LAB-1103.md; заголовок и остальное — в [5.11](../days/1105.md)):*

<!-- LAB-1103.md:1076 -->
  - TD 3/1/1/5, TU 3/0/3/4, HT 2/2/2/4.

*[…] строки этой записи между предыдущим куском и этим — в: [5.11](../days/1105.md), [ST, C30, AC, RT, SC, RT2, STAC](../1104/ST-AC-RT-SC-blocks.md)*

<!-- LAB-1103.md:1080 -->
- Каталог инструментов на вердикты не влияет. Прятанье убирает чтение исходников, но не двигает первую правку и не меняет V.

## Код

<!-- LAB-1103.md:958–1032 -->
**Код пробы** (приписано 10.11). Из кода убран в a13b543: в develop осталась одна база. Последний коммит с этим кодом — 951bc3b (`git show 951bc3b:ФАЙЛ`); номера строк в листинге — по нему.

`--tools-dir DIR` и `--hide-tools` (TD, TU, HT)

```python
# nrhsi/editor/work.py:141-150
def tt(s):
    """5.11 --tools-dir / --hide-tools: имена инструментов в тексте, который видит писатель."""
    if C.HIDE_TOOLS:
        for a, b in ((" (a copy of it is in `tests/orig_src/`)", ""), ("python3 tests/rerun.py", "rerun"),
                     ("python3 tests/smoke.py", "smoke"), ("`tests/rerun.py`", "`rerun`"), ("`tests/smoke.py`", "`smoke`"),
                     ("tests/rerun.py", "rerun"), ("tests/smoke.py", "smoke")):
            s = s.replace(a, b)
        assert "tests/" not in s, s[max(0, s.find("tests/") - 80):s.find("tests/") + 40]
        return s
    return s if C.TOOLS_DIR == "tests" else s.replace("tests/", C.TOOLS_DIR + "/")

# nrhsi/editor/work.py:153-169
def tool_run(run, name, args=""):
    """Запуск rerun/smoke харнессом -> (ok, out, full). --hide-tools: из каталога вне копии, в песочнице с правом чтения
    этого каталога; иначе python3 <tools>/<name>.py в обычной песочнице."""
    if not C.HIDE_TOOLS:
        ok, out, full, _, _ = F.bash_output(f"python3 {C.TOOLS_DIR}/{name}.py{args}", run.root, run.prof)
        return ok, out, full
    env = {"PATH": f"{F.BIN}:/usr/bin:/bin", "LANG": "en_US.UTF-8", "HOME": run.root, "PYTHONDONTWRITEBYTECODE": "1",
           "PYTHONPATH": F.SITE}
    try:
        p = subprocess.run(["sandbox-exec", "-f", run.prof + ".tools", "/bin/bash", "--noprofile", "--norc", "-c",
                            f"python3 {C.HIDDEN}/{name}.py{args}"], cwd=run.root, env=env, capture_output=True,
                           text=True, timeout=F.CMD_TIMEOUT * 6, stdin=subprocess.DEVNULL)
        full, ok = (p.stdout + p.stderr).replace(C.HIDDEN + "/", "").strip(), p.returncode == 0
    except subprocess.TimeoutExpired:
        full, ok = f"Error: {name} did not finish in time.", False
    out = full if len(full) <= F.OUT_CHARS else full[:F.OUT_CHARS] + f"\n[... {len(full)} characters in all]"
    return ok, out, full

# nrhsi/editor/tools.py:34-46
m = (re.match(r"(rerun|smoke)((?: [\w-]+)*)((?: \| (?:head|tail|grep|wc|nl|sed)\b[^;&`$<>(){}|]*)*)$", key)
     if C.HIDE_TOOLS else None)       # 5.11 --hide-tools: rerun и smoke — команды харнесса, можно с | head и т.п.
if C.HIDE_TOOLS and not m and re.match(r"(rerun|smoke)\b", key):
    return ("Error: rerun and smoke run on their own; only | head, tail, grep, wc, nl or sed may follow "
            "them."), False
if m and key not in run.seen:
    if m.group(1) == "smoke" and m.group(2):
        return "Error: smoke takes no arguments.", False
    ok, out, full = WK.tool_run(run, m.group(1), (m.group(2) or "") + (m.group(3) or ""))
    st["denied"] += not ok
    run.seen[key] = (st["tool_calls"], out)
    res.update(ok=ok, full_chars=len(full), truncated=len(full) > len(out))
    return out, False

# nrhsi/editor/work.py:196-198
td = C.HIDDEN if C.HIDE_TOOLS else f"{v}/{C.TOOLS_DIR}"     # 5.11: каталог инструментов
if C.HIDE_TOOLS and os.path.lexists(td):
    shutil.rmtree(td)

# nrhsi/editor/work.py:205-208
if C.HIDE_TOOLS:      # src/ — копии, а не соседа файла
    old = 'os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")'
    assert sm.count(old) == 1
    sm = sm.replace(old, repr(f"{v}/src"))

# nrhsi/editor/work.py:224-226
if C.HIDE_TOOLS:
    assert py.count("ROOT = os.path.dirname(HERE)") == 1
    py = py.replace("ROOT = os.path.dirname(HERE)", f"ROOT = {v!r}")

# nrhsi/editor/work.py:247-250
if C.HIDE_TOOLS:      # 5.11: для запуска rerun/smoke харнессом — то же + чтение каталога инструментов
    with open(p + ".tools", "w") as f:
        f.write(F.profile_text(root) + f'(allow file-read* (subpath "{C.HIDDEN}"))\n')
    F._PROFILES.append(p + ".tools")
```


## Связанные записи

- [5.11](../days/1105.md): «Чтение очереди писателя, часть 2»: сводка V/P/B/x, решение о V? на 09_TU
- [5.11](../days/1105.md): «Пробы с исходом по построению»: «читали исходник инструментов: HT 0»
- [G6](../1110/G6-bash-count.md): кандидат G6 (10.11) снят по итогу этой пробы
