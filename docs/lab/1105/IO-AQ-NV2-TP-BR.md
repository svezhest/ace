# IO, AQ, NV2, TP, BR — блок «всё, что можно»

[Указатель проб](../INDEX.md) · хронология: [5.11](../days/1105.md), [6.11](../days/1106.md) · как устроено — [README](../README.md)

<!-- LAB-1103.md:1553–1570 -->
## Блок «всё, что можно» (05.11, пользователь: «пробуй все что можно»), коммит d0ff3d9
Все варианты — добавки. Без флагов системный промпт байт в байт прежний (md5 сверен; git stash — только при пустой очереди, ps проверен).
| плечо | флаги | база | гипотеза |
|---|---|---|---|
| IO | --rerun --auto-check --intent-opt | AC | поля намерения необязательны: нет отказов, зеркало — только когда писатель сам сказал |
| AQ | --rerun --auto-check --ask-changed | AC | после правки — вопрос «Runs that passed in the log and go differently now: 3, 8. Is that what this edit is for?»; на вопрос модель отвечает, мимо списка проходит |
| NV2 | --rerun --navigator --nav-v 2 | W1, NV | пример начинается с места из наблюдения (sed по цитате → grep по именам → вспомогательная), без обзора |
| TP | --rerun --plan-line | W1 | планирование тикета в ответе: «Before an edit, write in your reply how the run… will go once the edit is in…» (не отдельный шаг) |
| BR | --rerun --broad-example | W1 | выдуманный пример: правка шире задуманного → rerun показывает удачные → узкая правка, только тикет |
- 10 наблюдений × seed 1 на каждое плечо (50 сессий). Мерка: вердикты руками; для NV2 — nav.py; для IO — доля заполненных полей и реакция; для AQ — ответ на вопрос (откат/сужение/«да, задумано»); для TP — есть ли план в ответе и совпал ли он с правкой.
- Проверено до запуска: ask_changed на 02_GC_s1 → «3, 8, 20», на 02_GC_s5 → «3», на мёртвой 02_GC_s4 → нет вопроса.
- Проверка механики на 00 (первые 5 сессий):
  - IO: необязательные поля не заполнены ни разу (`expect_runs` None в обеих правках), сверка не показывалась. Без обязательности 9B полем не пользуется. IO на деле равно AC — так и считать.
  - AQ: вопрос пришёл после первой правки.
  - NV2: всё равно начал с `cat README.md` и ls.
  - TP: в ответах есть объяснение изъяна; план прогона — читать.
  - BR: пример на месте, правки идут.

<!-- LAB-1103.md:1812–1840 -->
### Блок IO/AQ/NV2/TP/BR: итог (6.11, 02:20)
По 10 сессий на вариант, seed 1. Механический фильтр `filt.py`, потом каждая правка прочитана руками. Мерка вердикта та же, что в блоке 3 (READ.md).

| набл. | IO | AQ | NV2 | TP | BR |
|---|---|---|---|---|---|
| 00 | x: тикет не задет | B: цикл наблюдений периода 3 → стоп, задет удачный 1 | x: падение | B: любое повторное наблюдение → стоп, задеты 22 удачных | x: `all([])` на пустой истории → стоп на первом шаге во всех 30 |
| 01 | B: `[-2]` | B: `[-2]` | x: сужено до тройного повтора, тикет не задет | B: `[-2:]` | x: поиск кратчайшего цикла мёртв на тикете |
| 02 | V: оба `continue` убраны, повтор исполняется (сообщение стало «Call complete_task») | P: строка «never repeat» в промпте | B: повтор → эпизод кончен | B: то же | x: в историю пишется копия, сравнение то же; ложное «the task will end on its own» |
| 03 | x: «did not move the task forward» — та же ложь другими словами | x: сравнение сдвинуто на весь ответ, сообщение то же | V: «If it did not work… try a different step» | x: случайно живая (условие на устаревшем `output`) | x: «which failed» осталось для непустого вывода |
| 04 | x: тикет не задет | x: тикет не задет | x: падение | x: только docstring | B: любой недавний такой же код; задеты 2 удачных |
| 05 | x: у вопроса убран answer | P?: фраза убрана, answer цел, но снят маркер `ASSISTANT:` | x | x | x: правило + answer убран |
| 06 | V: блок действия не из списка | V | x: ключ `ctx["raw"]`, мёртв | V | V |
| 07 | V: ответ без вызова не тратит ход | V | x: → эпизод кончен | x: падение | x: → эпизод кончен |
| 08 | x | x | x | x | x: падение |
| 09 | x: хук «сам выводит ответ» мёртв на тикете | P: «пример — иллюстрация» | P: `num_playlists = len(playlists)` + «не сценарий» | P: «не сценарий» | 0 правок |

V/P/B/x: IO 3/0/1/6, AQ 2/3/2/3, NV2 1/1/1/7, TP 1/1/3/5, BR 1/0/1/8. База W1 s1 2/2/1/5.
- При одном seed и 27 % переворотов (GC-6) это в пределах шума. Ни один вариант базу не превзошёл.
- Источник V тот же: 02, 03, 06, 07 (класс А). На 00, 04, 08 V нет ни в одном варианте.
- **IO.** Необязательные поля не заполнены (проверено на 00), по сути это база.
- **AQ.** Вопрос пришёл в 6 сессиях из 10. Реакция:
  - разобрался с задетыми прогонами — 3: 00 смотрит run 1 и правит; 01 перезапускает 8 и 20; 08 перебирает 19/21/32/34;
  - отмахнулся — 2: 03 «confirms the fix works»; 06 «hook only fires when genuinely not admissible», затем finish, хотя задеты 14 удачных;
  - 08 при этом пишет «fixed run 40 — now match the log to the end», хотя тикет не задет, то есть отсутствие изменений читает как починку.
  - Вопрос правок не испортил, но и сужения не дал: 00 и 01 остались B.
- **NV2.** Худший: 2 падения, мёртвый ключ на 06. Навигатор со стартом с sed по ссылкам не помог (nav.py — отдельно).
- **TP.** План в ответах есть, правки шире (TP 3 B).
- **BR.** Пример «широкая правка → rerun → сужение» не сузил ни одну. На 00 сломал всё (`all([])`).

## Код

<!-- LAB-1103.md:1571–1665 -->
**Код пробы** (приписано 10.11). Из кода убран в a13b543: в develop осталась одна база. Последний коммит с этим кодом — 951bc3b (`git show 951bc3b:ФАЙЛ`); номера строк в листинге — по нему.

`--intent-opt` (IO): остальное — как `--intent` в записи «Проба IN»

```python
# nrhsi/editor/prompt.py:117-119
INTENT_OPT_LINE = (" With an edit you may say what you expect it to do: expect_runs, the numbers of the recorded runs in "
                   "logs/ whose course it changes, and expect, what the harness will do differently in them; the checks "
                   "after the edit then compare this with the runs that did change.")

# nrhsi/editor/cli.py:166-167
if a.intent_opt:
    a.intent = True
```

`--ask-changed` (AQ)

```python
# nrhsi/editor/gate.py:138-145
def ask_changed(run):
    """--ask-changed: удачные в логе прогоны, что после правки идут иначе -> вопрос (None, если таких нет или промпт другой)."""
    ch, passed, prompt = changed_runs(run.last_rerun or "", run.root)
    hit = sorted(ch & passed)
    if prompt or not hit:
        return None
    return (f"Runs that passed in the log and go differently now: {', '.join(map(str, hit))}. "
            "Is that what this edit is for?")

# nrhsi/editor/tools.py:105-109
if C.ASK_CHANGED:
    q = GA.ask_changed(run)
    if q:
        text += "\n" + q
        rec["asked"] = True
```

`--nav-v 2` (NV2)

```python
# nrhsi/editor/prompt.py:165-179
NAV_EXAMPLE2 = """# Example: finding what a change needs (another repository)
Observation: "Exported reports lose their last row: write_rows() (src/export.py:40-52) stops one row early."

bash(command="sed -n '36,56p' src/export.py")
def write_rows(out, table):
    for i in range(n_rows(table) - 1):
    ...

bash(command="grep -n 'n_rows\\|write_rows(' src/*.py")
src/export.py:18:def n_rows(table):
src/export.py:40:def write_rows(out, table):
src/report.py:63:    write_rows(f, table)

bash(command="sed -n '16,24p' src/export.py")
..."""
```

`--plan-line` (TP)

```python
# nrhsi/editor/prompt.py:182-184
PLAN_LINE = ("- Before an edit, write in your reply how the run the observation is about will go once the edit is in: "
             "at which step the harness acts differently, and what the agent then sees and does. Then make the edit "
             "that does that.")

# nrhsi/editor/cli.py:186-188
if a.plan_line:
    assert "\n# How to work\n" in esys
    esys = esys.replace("\n# How to work\n", "\n# How to work\n" + P.PLAN_LINE + "\n")
```

`--broad-example` (BR)

```python
# nrhsi/editor/prompt.py:187-198
BROAD_EXAMPLE = """# Example: an edit that changes more than the run it is for (another repository)
Observation: "Run 7 shows a stale price: get_price() (src/cache.py:20-31) returns the cached value without checking its age."

edit(path="src/cache.py", old_string="    return CACHE[item]", new_string="    return fetch(item)")
python3 tests/rerun.py prints:
runs 2, 5, 7, 9 (1 failed, 3 passed): diverges at model call 3: what the model sees differs from the log
runs 1, 3, 4, 6, 8 (2 failed, 3 passed): no changes (same as the log to the end)

edit(path="src/cache.py", old_string="    return fetch(item)", new_string="    if time.time() - STAMP[item] > MAX_AGE:\n        return fetch(item)\n    return CACHE[item]")
python3 tests/rerun.py prints:
run 7 (failed): diverges at model call 3: what the model sees differs from the log
runs 1, 2, 3, 4, 5, 6, 8, 9 (2 failed, 6 passed): no changes (same as the log to the end)"""

# nrhsi/editor/cli.py:183-185
if a.broad_example:
    assert a.rerun and "\n# How to work\n" in esys
    esys = esys.replace("\n# How to work\n", "\n" + P.BROAD_EXAMPLE + "\n\n# How to work\n")
```


## Связанные записи

- [6.11](../days/1106.md): «Где писатель ошибается на 00, 04, 08 (блок IO..BR, чтение рассуждений)» и «Поправки автора к разбору 00/04/08»
- [6.11](../days/1106.md): «План на 6.11, если автор не отвечает», п. 2
- [6.11](../days/1106.md): «Мерка: пары по месту расхождения»: ночной блок так не разобран
