# ST, C30, AC, RT, SC, RT2, STAC — блоки 1–2: этапы против C30; авто-проверка, rerun-инструмент, scratch

[Указатель проб](../INDEX.md) · хронология: [4.11](../days/1104.md), [5.11](../days/1105.md) · как устроено — [README](../README.md)

*Из записи «17. Как писатель тратит bash, 4.11 вечер» (LAB-1103.md; заголовок и остальное — в [4.11](../days/1104.md)):*

<!-- LAB-1103.md:686–694 -->
- **Решения автора, 4.11 ~20:30:** абляция — на W1; этапы — проверка начинается с первой правки (абляцию вариантов — потом); scratch для записи — попробовать («главное, чтобы 9B не запуталась, как с логами»); rerun с ожиданием: change=false → «ok, no changes» / «failed!: diff», change=true → «ok: diff» / «failed: no changes!».
- **Сделано (коммит «writer: --stages, --auto-check, --rerun-tool, --scratch»):**
  - `--stages R,K`: R bash на чтение; первая применённая правка (или конец R) начинает проверку — ещё K bash; после неё правки не применяются (`--checked`). Сообщения: в ответе первой правки «This is your first edit, so the check part starts: you have K bash calls left…»; при конце R без правки — note «You have used the R bash calls for reading…».
  - `--auto-check`: в ответе каждой применённой правки — новые предупреждения pyflakes, smoke (вывод при падении, иначе «runs without errors»), rerun (до 2500 символов); bash не тратится.
  - `--rerun-tool`: инструмент `rerun(change, run)`; ok/failed по ожиданию, как сказал автор; ядро повтора — вне копии (нет tests/rerun.py, rerun_core.py, orig_src); README — тот же текст для инструмента, пример `rerun(change=true)` → `ok:` и `rerun(change=false, run=3)` → `failed!:`.
  - `--scratch`: механика scratch/ исследователя (запись только туда, «there is no /tmp»).
  - Проверено на заглушке без модели (App r5): rerun(change=false) на нетронутом → «ok, no changes», rerun(change=true, run=19) → «failed: no changes!», без change — отказ; запись в scratch/ работает; конец чтения без правки → note и +K; правка на 4-м bash → предел 19; после конца — правка «not applied»; проверки в ответе правки показывают расхождение в 3, 9, 19. Промпты — diff против базы по каждому флагу.
- **Очередь за абляцией (70 сессий):** блок 1 — `NN_ST_s{1,2}` (`--rerun --stages 15,15`) против `NN_C30_s{1,2}` (`--rerun --bash-limit 30 --checked`: тот же бюджет и то же «после конца не применяется», без этапов), 10 наблюдений × 2 seed; блок 2 — `NN_AC` (`--auto-check`), `NN_RT` (`--rerun-tool`), `NN_SC` (`--scratch`), каждый на W1, 10 × seed 1. Мерка: первая правка (номер bash), доля правок вслепую, процессный брак, верные — ручным чтением; для RT — как часто change совпадает с итогом и что писатель делает после failed.

<!-- LAB-1103.md:897–900 -->
### Ошибка: в этапах (`--stages`) правки после конца bash применялись
- `C.CHECKED` выставлялся из `a.checked` до разбора `--stages`, а `--stages` включал `a.checked` позже — в харнесс не доходило. Промпт обещал «edits are not applied», харнесс применял; в контроле C30 (`--checked`) — не применял. Сравнение было бы нечестным. На заглушке я проверял лимиты и переход, но не отказ правки после конца — моя ошибка.
- 00–02_ST_s1 (готовы) отложены как `*_STnochk_s1`, 03/04 (шли) остановлены; перезапуск с исправлением.

<!-- LAB-1103.md:935–942 -->
### Итог: блок 1 (этапы против C30) и блок 2 (AC, RT, SC) (5.11, ручное чтение 70 сессий)
- Таблицы и вердикты по каждой сессии — `runs/wvar_1104/READ.md`.
- Блок 1 (20 + 20, seed 1–2): ST — V 4, P 3, B 6, x 5, без правок 2; C30 — V 4, P 1, B 2, x 9, без правок 4. V поровну; у ST меньше мёртвых и больше живых (V+B: 10 против 6). Правок вслепую 0 в обоих (--checked). Шум: один seed на пару, ±2 сессии — разброс.
- Блок 2 (по 10, seed 1): AC — V 2, P 1, B 4, x 3; RT — V 1, B 3, x 6; SC — V 2, B 2, x 6; база W1 — V 2, P 2, B 1, x 5. Ни один не поднял V; AC меньше мёртвых (3 против 5).
- RT: rerun на нетронутом src почти исчез (1 вызов до правки), но «ok» на правку промпта — ложное подтверждение; «failed: no changes!» писатель лечит новыми мёртвыми правками (08).
- Ошибки по наблюдениям те же, что в серии W: 01/04 — «любой недавний код»; 05 — убрать answer у вопроса; 07 — «эпизод кончен» вместо «не тратить ход»; 08 — 0 живых (как всегда). Новое: 00 впервые живая на тикете (00_ST_s1, 00_AC, 00_RT; все B).
- Не пробовали: второй seed для блока 2; этапы + AC вместе.

<!-- LAB-1103.md:943–947 -->
### rerun с ожиданием: expect_diff (5.11, решение пользователя)
- Пользователь: «ok» на правку промпта формально верен (промпт заменён); что писатель в 05 правил промпт — его выбор. Моё «ложное подтверждение» — неверно; заплатка «cannot check» (ece0128) заменена.
- Новое: `rerun(expect_diff, run)`, expect_diff обязателен: none (прогоны как в логе) | prompt (изменён промпт — расходятся на промпте) | control (изменён код харнесса — расходятся с какого-то места). Совпало: «ok, no changes» / «ok: <вывод>»; нет: «failed: no changes!» / «failed!: <вывод>». Описание — в схеме инструмента, строке Tools и README копии. Проверено заглушкой (9 сочетаний, отказ без поля).
- 05_RT2, 09_RT2 стартовали в 05:10 со старым кодом — остановлены (мои), перезапуск очередью с новым.

*Из записи «Чтение очереди писателя, часть 1 (05.11)» (LAB-1103.md; заголовок и остальное — в [5.11](../days/1105.md)):*

<!-- LAB-1103.md:1053–1056 -->
- RT2 (обязательное expect_diff):
  - 05_RT2: rerun не звал ни разу; правка в промпте = буквальное отрицание (пример-вопрос переделан в «без answer») → B.
  - 09_RT2: 1 вызов, expect_diff=prompt, получил ok; YOUR_ANSWER + общий абзац «пример не твоя задача» → P.
  - «failed» не выпал ни разу, влияние на поведение не видно.

*Из записи «Чтение очереди писателя, часть 2 (05.11) — таблицы в runs/wvar_1104/READ.md» (LAB-1103.md; заголовок и остальное — в [5.11](../days/1105.md)):*

<!-- LAB-1103.md:1074–1075 -->
  - STAC_s1 2/0/1/7, STAC_s2 2/0/1/7.
  - AC_s2 1/0/3/6, SC_s2 1/1/1/7.

*[…] строки этой записи между предыдущим куском и этим — в: [TD, TU, HT](../1105/TD-TU-HT-tools-dir.md), [5.11](../days/1105.md)*

<!-- LAB-1103.md:1079 -->
- STAC не лучше ST: P на 05 пропал. Правки на 05 — буквальное отрицание (6 из 7), только HT сохранил answer у вопроса.

## Код

*Часть блока «Код пробы» записи «17. Как писатель тратит bash, 4.11 вечер»; начало блока, с оговоркой о коммите 951bc3b, — в [W1L](W1L-bash-limit.md):*

<!-- LAB-1103.md:705–890 -->
`--stages R,K` (ST, STAC)

```python
# nrhsi/editor/prompt.py:110-113
STAGES_LINE = ("- bash: the first STAGE_R calls are for reading. Your first edit starts the check part: from then on you "
               "have STAGE_K more bash calls to check your edits (if the STAGE_R calls run out before you edit, the check "
               "part starts then). After the check part, edits can no longer be checked and are not applied: only "
               "finish remains, and the session ends.")

# nrhsi/editor/cli.py:144-147
if a.stages:
    line = P.STAGES_LINE.replace("STAGE_R", str(C.STAGES[0])).replace("STAGE_K", str(C.STAGES[1]))
    esys = esys.replace(P.fill(P.CHECKED_LIMIT_LINE), line)
    assert line in esys

# nrhsi/editor/cli.py:231-235
if a.stages:
    C.STAGES = tuple(int(x) for x in a.stages.split(","))
    assert len(C.STAGES) == 2 and not a.bash_limit and not a.goal_k, "--stages R,K; без --bash-limit и --goal-k"
    C.BASH_LIMIT, a.checked, C.CHECKED = sum(C.STAGES), True, True   # C.CHECKED уже выставлен выше — ставим и его
    C.STEP_BUDGET = max(C.STEP_BUDGET, C.BASH_LIMIT + 35)

# nrhsi/editor/state.py:27-28
self.bash_limit = C.STAGES[0] if C.STAGES else C.BASH_LIMIT     # --stages: сдвигается в начале проверки
self.stage2 = False                # --stages: часть проверки началась

# nrhsi/editor/phase.py:30-33
elif run.st["bash_calls"] >= run.bash_limit and C.STAGES and not run.stage2:
    run.stage2, run.bash_limit = True, run.bash_limit + C.STAGES[1]
    run.note_user(f"You have used the {C.STAGES[0]} bash calls for reading, so the check part starts: make your "
                  f"edits; you have {C.STAGES[1]} bash calls left to check them.")

# nrhsi/editor/tools.py:96-99
if C.STAGES and not run.stage2:
    run.stage2, run.bash_limit = True, run.st["bash_calls"] + C.STAGES[1]
    text += (f"\n\nThis is your first edit, so the check part starts: you have {C.STAGES[1]} bash calls "
             "left to check your edits.")
```

`--auto-check` (AC): проверка в ответе edit осталась в базе; убрана строка промпта тех серий (её заменила строка CL, запись «TKK и CL»)

```python
# nrhsi/editor/prompt.py:125-126
AUTO_CHECK_LINE = (" After each edit that is applied, pyflakes, python3 tests/smoke.py and RERUN_NAME are run on src/; "
                   "their output comes with the edit's answer and uses no bash calls.")

# nrhsi/editor/cli.py:154-159
if a.auto_check:
    chk = next(x for x in (P.RERUN_TOOL_CHECK_LINE, P.RERUN_CHECK_LINE, P.CHECK_LINE) if x in esys)
    add = P.AUTO_CHECK_LINE.replace("RERUN_NAME", "rerun" if a.rerun_tool else "python3 tests/rerun.py")
    if not a.rerun:
        add = add.replace(", python3 tests/smoke.py and python3 tests/rerun.py", " and python3 tests/smoke.py")
    esys = esys.replace(chk, chk + add)
```

`--rerun-tool` (RT, RT2)

```python
# nrhsi/editor/prompt.py:127-131
RERUN_TOOL_LINE = ("- rerun(expect_diff, run): replays the runs in logs/ on the current src/ (see README.md). "
                   "expect_diff is what you expect it to show: none (the runs go as in the log), prompt (you changed "
                   "the prompt) or control (you changed the harness code, so the runs go differently from some point). "
                   "It answers ok or failed (did the runs go as you expected), then what changed; run: one run in "
                   "detail.")

# nrhsi/editor/prompt.py:132-134
RERUN_TOOL_CHECK_LINE = ("- Check each change: run python3 tests/smoke.py and the rerun tool (see README.md), and read the "
                         "changed lines together with the code that calls or uses them. If rerun shows no changes in "
                         "the runs an observation is about, your change may have missed.")

# nrhsi/editor/schema.py:38-50
RERUN_SCHEMA = {"type": "function", "function": {
    "name": "rerun", "description": "Replay the runs in logs/ on the current src/ (see README.md) and say whether they "
    "went as you expected.",
    "parameters": {"type": "object", "properties": {
        "expect_diff": {"type": "string", "enum": ["none", "prompt", "control"], "description":
                        "What you expect the replay to show on the current src/. none: the runs go exactly as in the "
                        "log (src/ as at the start, or a change that should not touch these runs). prompt: you changed "
                        "the prompt, so the runs differ from the log at the prompt and nothing after it is compared. "
                        "control: you changed the harness code, so from some point on the runs go differently from "
                        "the log."},
        "run": {"type": "integer", "description": "One run, shown in detail. Without it: all runs, one line per group "
                "of runs that behave the same way."}},
        "required": ["expect_diff"]}}}

# nrhsi/editor/cli.py:148-153
if a.rerun_tool:
    for old, new in ((P.RERUN_CHECK_LINE, P.RERUN_TOOL_CHECK_LINE), (P.EDIT_TOOL_LINE, P.EDIT_TOOL_LINE + "\n" + P.RERUN_TOOL_LINE),
                     ("what python3 tests/rerun.py prints on them", "what rerun prints on them")):
        if old in esys or old.startswith("what"):
            esys = esys.replace(old, new)
    assert P.RERUN_TOOL_LINE in esys and P.RERUN_TOOL_CHECK_LINE in esys and "tests/rerun.py" not in esys

# nrhsi/editor/tools.py:113-135
def rerun_call(run, args, res):
    """--rerun-tool: rerun(expect_diff, run) -> ok / failed по ожиданию (none | prompt | control), затем вывод повтора."""
    ex, n = args.get("expect_diff"), args.get("run")
    if ex not in ("none", "prompt", "control"):
        run.st["bad_call"] += 1
        res["format_fail"] = "bad_args"
        return "Error: expect_diff is required: none, prompt or control.", False
    if n is not None:
        try:
            n = int(n)
        except (TypeError, ValueError):
            run.st["bad_call"] += 1
            res["format_fail"] = "bad_args"
            return "Error: run must be a run number.", False
    run.st["reruns"] = run.st.get("reruns", 0) + 1
    out, changed = GA.rerun_output(run, n)
    top = [l for l in out.splitlines() if l.strip() and not l[0].isspace() and not l.startswith("…")]
    got = ("none" if not changed else
           "prompt" if top and all("the prompt differs from the log" in l for l in top) else "control")
    res.update(expect_diff=ex, got_diff=got)
    if ex == got:
        return ("ok, no changes" if got == "none" else "ok:\n" + out), False
    return ("failed: no changes!" if got == "none" else "failed!:\n" + out), False

# nrhsi/editor/gate.py:83-96
def rerun_output(run, n=None):
    """Вывод повтора прогонов на текущем src/ -> (текст, есть ли расхождение хоть в одном прогоне).
    --rerun-tool: ядро editor/rerun.py вне копии (в копии его нет), старый src — вид; иначе tests/rerun.py в песочнице."""
    if C.RERUN_TOOL:
        cmd = [sys.executable, RERUN_CORE, "--bench", C.BENCH, "--src", f"{run.root}/src", "--logs", f"{run.root}/logs",
               "--old", f"{C.VIEWS[C.BENCH]}/src"] + ([str(n)] if n is not None else [])
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        full = (p.stdout + p.stderr).strip()
    else:
        _, _, full = WK.tool_run(run, "rerun", f" {n}" if n is not None else "")
        full = full.strip()
    heads = [l for l in full.splitlines() if l and not l[0].isspace()]
    changed = any("no changes" not in l for l in heads)
    return clip(full, F.OUT_CHARS), changed

# nrhsi/editor/work.py:32-46
def rerun_tool_readme():
    """--rerun-tool (4.11): тот же текст README про повтор — для инструмента rerun(expect_diff, run)."""
    t = RERUN_README
    for old, new in (("- `tests/rerun.py` — replays", "- the rerun tool — replays"),
                     (" (a copy of it is in `tests/orig_src/`)", ""),
                     ("`python3 tests/rerun.py` prints one line per group of runs that behave the same way; "
                      "`python3 tests/rerun.py N` shows run N in detail, with the line of `logs/run_N.jsonl`.",
                      "rerun without run prints one line per group of runs that behave the same way; rerun with run=N "
                      "shows run N in detail, with the line of `logs/run_N.jsonl`. Before that, rerun says whether the "
                      "runs went as you expected with expect_diff: `ok` or `failed`."),
                     ("$ python3 tests/rerun.py\n", 'rerun(expect_diff="control")\nok:\n'),
                     ("$ python3 tests/rerun.py 3\n", 'rerun(expect_diff="none", run=3)\nfailed!:\n')):
        assert t.count(old) == 1, old
        t = t.replace(old, new)
    return t
```

`--scratch` (SC)

```python
# nrhsi/editor/prompt.py:135
SCRATCH_NOWRITE = "Nothing can be written with it."

# nrhsi/editor/prompt.py:136-137
SCRATCH_WRITE = ("Files can be written only in scratch/ (empty at the start; > scratch/NAME, or from python3); "
                 "everything else is read-only, and there is no /tmp.")

# nrhsi/editor/schema.py:53-62
def bash_schema():
    """--scratch: в описании bash — запись только в scratch/."""
    from . import cfg as C
    if not C.SCRATCH:
        return BASH_SCHEMA
    f = dict(BASH_SCHEMA["function"])
    f["description"] = f["description"].replace("Run a read-only shell", "Run a shell").replace(
        "nothing can be written", "only scratch/ can be written")
    assert f["description"] != BASH_SCHEMA["function"]["description"]
    return {"type": "function", "function": f}

# nrhsi/editor/cli.py:176-179
if a.scratch:
    esys = esys.replace(P.SCRATCH_NOWRITE, P.SCRATCH_WRITE).replace("a read-only shell in", "a shell in").replace(
        F.PYTHON_LINE, F.PYTHON_SCRATCH_LINE.replace("SCRATCH/", F.SCRATCH_DIR + "/"))
    assert P.SCRATCH_WRITE in esys and "read-only shell" not in esys

# nrhsi/editor/work.py:211-212
if C.SCRATCH:
    os.makedirs(f"{v}/{F.SCRATCH_DIR}")
```


## Связанные записи

- [5.11](../days/1105.md): «Чтение очереди писателя, часть 1/2»: сводка V/P/B/x по вариантам
- [5.11](../days/1105.md): «Пробы с исходом по построению»: «вслепую 0» — ноль по построению
- [01m](../1105/01m-input-wording.md): 01m_STAC — изменённый вход на плече STAC
