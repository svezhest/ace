# TKP — факт о задетом удачном прогоне (`--ticket-passed`)

[Указатель проб](../INDEX.md) · хронология: [6.11](../days/1106.md) · как устроено — [README](../README.md)

<!-- LAB-1103.md:2574–2590 -->
### TKP: факт о задетом удачном прогоне (6.11, 11:31 по `date`)
- **Повод.** В TKS/TKV на трёх seed 12 правок B, и большинство из них — широкое условие, задевающее удачные прогоны. Писатель видит в выводе rerun только номера этих прогонов. Вопрос «Is that what this edit is for?» уже пробовали (AQ): разбирался в 3 из 6 случаев, сузить не удалось ни разу. Здесь по аналогии с TKV вместо вопроса даётся факт.
- **Коммит bd4c669, флаг `--ticket-passed`** (нужен `--ticket-values`). К проверке по тикету добавляется строка. Берётся первый удачный в логе прогон не из тикета, который с кодом правки (тексты — как в виде) идёт иначе: «Run 3 passed in the log (of 3 such runs: 3, 8, 15); with your code it goes differently from model call 11 on: your `if …` at src/F:L was true N times (at its last run, before model call K: значения)».
  - Условие засчитывается, только если тело выполнялось и само условие истинно на последнем выполнении (скрытая проба `bool(cond)`, если условие вычислимо без побочных эффектов). Так охраны вроде `if len(pairs) < 6:` отсекаются. `return <выражение>`, вернувшие True, тоже считаются.
  - Показываются до двух, по возрастанию числа срабатываний: то, после чего прогон разошёлся, обычно срабатывало раз-другой.
  - Элементы коротких списков — с формой (`__shape2__`, только под этим флагом).
- **Оффлайн на итоговых src B-сессий:**
  - 04_TKS_s3: «run 3 … from model call 11: your `if drifting_steps >= TASK_DRIFT_LIMIT:` … was true 1 time (`drifting_steps` = 6, `TASK_DRIFT_LIMIT` = 6); your `if api is not None and api != "supervisor":` … was true 8 times (`api` = 'spotify')»;
  - 01_TKS_s3: «`if code in recent:` was true 1 time (`code` = 'passwords=apis.supervisor.show_account_passwords()\nprint(passwords)', …)». Видно, что сработало на законном повторе шага;
  - 00_TKS_s3: «`return _stuck_in_a_cycle(history)` returned True 1 time».
- **Мой промах при разработке, исправлен до вреда.** Форма коротких списков сначала была включена под `__shape__`, а `editor/rerun.py` gate вызывает подпроцессом на каждой проверке. Значит, она сразу действовала бы на идущие TKW. Вынес её под `__shape2__` и проверил: в TKW_s1 00–03 к тому моменту не было ни одной проверки. gate без флага по поведению равен 2df0de8. `--dry` совпадает байт в байт.
- **Сессии `wv_NN_TKP_sS`** = TKW + `--ticket-passed`, S = 1–3, 30 сессий в очереди после TKW. Пара — TKW того же seed: сессии расходятся только с первой проверки, где задет удачный прогон.
- **Мерка:**
  - доля B против TKW;
  - реакция на факт: сузил, отмахнулся или проигнорировал;
  - не стало ли больше x: сужение может убить живую правку.

<!-- LAB-1103.md:2774–2783 -->
### TKP s1 (6.11, 13:41 по `date`)
- 7 из 10 итоговых правок совпадают с TKW s1. Отличаются 00, 08, 09; вердикты те же. V/P/B/x = 1/1/1/7, как у TKW s1.
- **Факт о задетом удачном прогоне показан в 4 сессиях (00, 03, 06, 08), 5 раз. Реакции нет ни в одной:**
  - **03, 06:** факт пришёл последней проверкой, уже после «You have used all 25 bash calls». Писатель пишет итог и finish. В 06 факт показал `action` = 'go' (действие режется до первого слова) — ровно тот брак, из-за которого 06 x. Не замечен.
  - **00:** факт («`return len(set(observations[-3:])) == 1` returned True 1 time» в удачном 2) идёт после Failed по тикету. Писатель разбирает только тикет.
  - **08:** дважды («`if cur in observations[-3:-1]:` was true 1 time … 'on the stoveburner 1, you see a pot 1.'» в удачном 3). Писатель: «Let me verify … passing runs remain unchanged», но bash уже нет.
- **Почему:** Ok по тикету (03, 06, 08 — последняя проверка) писатель читает как «готово», и строка после Ok не читается. При Failed (00) внимание целиком на тикете. **Факт о задетых нужен там, где он не конкурирует с тикетом:** например, когда тикет уже Ok, а bash ещё есть. Сейчас Ok часто приходит в самом конце.
- 09: хук на конец примера подставляет первый шаг примера (текст про Venmo из задачи прогона 8); на прогоне тикета код не меняется. x.
- **Дополнение к TKP s1: как кончились сессии с фактом после Ok.** 03 и 06 сами вызвали finish сразу после Ok и факта о задетых, хотя у них оставались финальные ходы (`FINAL_TURNS` = 3, правки в них проверяются). 08 упёрся в лимит ходов. **Ok по тикету писатель читает как «готово», хотя Ok значит только «изменение произошло»** (это задано так с начала TK). Гипотеза для следующей пробы, если s2/s3 покажут то же: при задетых удачных прогонах факт о них — в ту же строку Ok, а не отдельной строкой после неё. Пока не делаю: жду s2/s3.

<!-- LAB-1103.md:2784–2800 -->
### TKP s2 (6.11, 14:17 по `date`)
| | 00 | 01 | 02 | 03 | 04 | 05 | 06 | 07 | 08 | 09 | V/P/B/x |
|---|---|---|---|---|---|---|---|---|---|---|---|
| TKW s2 | x | x | V | P | x | x | V | x | V | x | 3/1/0/6 |
| TKP s2 | = x | = x | x | P | = x | x | V | = x | **x** | x | 1/1/0/8 |

- **02 — x, расхождение с TKW с хода 3, до любого факта (шум сервера).** Повтор кода теперь исполняется, но в `else` каждый обычный шаг получает «The previous step produced this output again», и код исполняется дважды. Писатель отбросил факт о задетых: «The rerun "divergence" for the other runs is expected and correct».
- **08 — x, и это мой брак.** Расхождение с TKW на ходе 15: на той же проверке значения `tail`/`head` показаны по-разному.
  - TKW: весь список до 160 символов, видна большая часть наблюдения.
  - TKP: короткий список поэлементно (`__shape2__`), а элемент-кортеж режется на 60 символах как целое («('examine dresser 1', 'on the dresser 1, you see a cellphone»).
  - Дальше писатель TKW дошёл до сравнения трёх пар с тремя предыдущими (V), писатель TKP — до `tail[0] == tail[2] == prev` (только период 1, на чередовании мёртво).
  - **Форма `__shape2__` у кортежей хуже исходной.** TKP получился не «TKW + факт о задетых», а «TKW + факт + испорченная форма коротких списков». Конфаунд моего изготовления.
- **06 — V, тот же итог, что TKW s2.** Факт о задетых («Run 9 passed in the log (of 15 such runs …); with your code it goes differently from model call 6 on», без условия) — **первая реакция за TKP:** «it diverges at model call 6, which might be a false positive (an action that the log itself treats as valid). `python3 tests/rerun.py 9 --at 6`». Итоговая правка не сузилась.
- 03 — P (как TKW). 05 x (у вопроса в примере убран answer), 09 x (разбор ролей примера регулярками, тикет не задет).
- **Факт о задетых в s2:** показан в 3 сессиях. Разобран — 1 (06), отброшен — 1 (02), проигнорирован с finish — 1 (03). Пока ни одного сужения.
- **Решение:** TKP s3 идёт той же версией (bd4c669), не трогаю, чтобы серия была однородной. Исправление формы (кортежи и списки — поэлементно рекурсивно) — в следующую версию, вместе с вопросом, ставить ли факт в строку Ok.

<!-- LAB-1103.md:2846–2861 -->
### TKP s3 и итог TKP (6.11, 14:51 по `date`)
- **s3:** 00 x (падение; расхождение с TKW постороннее, ход 17), 01 B, 02 V, 03 x, 04 B, 05 P, 06 x, 07 x, 08 B, 09 P. V/P/B/x = 1/2/3/4, как у TKW s3. Вердикт тот же во всех 6 парах по механизму.
- **Первое сужение от факта о задетых — 01_s3:**
  - факт: «Run 3 passed … `if code in recent:` was true 1 time (`code` = 'passwords=apis.supervisor.show_account_passwords()\nprint(passwords)', …)», то есть сработало на законном повторе шага;
  - писатель дважды менял окно, после второго факта (удачный 8): «run 1 is a strict 2-step alternation, while run 8 legitimately reuses a line from 6 steps ago. Let me make the check detect oscillation specifically»;
  - итог: `code == last_actions[-2]`. Задеты 2 удачных вместо 3 у TKW s3 (`code in last 5`), всё ещё B.
- **Остальные показы в s3:** 04 и 08 — писатель занят своей починкой (UnboundLocalError, подключение хука), факт не упоминает; 02 и 03 — факт без условия («goes differently from model call 4 on»), за ним сразу последняя правка.
- **Итог TKP за три seed:** 3/4/4/19 (TKW 5/4/4/17).
  - Пары по механизму: 0 улучшений вердикта. 1 ухудшение (08_s2) — от моего брака `__shape2__`, не от факта.
  - **Факт показан в 12 сессиях:**
    - разобран — 2 (06_s2: «might be a false positive», итог прежний; 01_s3: сузил, B остался);
    - отброшен — 1 (02_s2: «expected and correct»);
    - не замечен — 9: Ok и finish, конец bash, занят тикетом.
- **Вывод:** факт о задетых читается, когда писатель ещё правит и тикет уже Ok (01_s3). Этот механизм в одиночку не сужает до V. Ok как «готово» и бюджет остаются главными.
- TKP в базу дальше не беру. Следующие пробы — от TKV/TKD.

<!-- LAB-1103.md:2862–2871 -->
### Поправка автора: «задет удачный прогон» — не общо (6.11, 15:10 по `date`)
- **Автор о TKP:** правка может законно менять ход удачных прогонов. Пример: класс прогонов делится на три части, правка чинит одну и неизбежно трогает две другие. «Первый задетый удачный» — сигнал только для правок, которые должны быть узкими.
- **Отсюда же, найдено при пересмотре:**
  - **вердикт B — прокси той же эвристики, и применял я его непоследовательно:** 06 с 15 задетыми удачными — V, 01 `[-2]` с 2 задетыми — B. Что стало с задетыми, решает только замер на val;
  - **«повтор исполняется» (02 V)** опасен для кода с побочными эффектами (в App это повторный платёж или отправка);
  - **«не тратить ход» (06 V, 07 V)** открывает ту же дыру «до конца контекста», что в 02;
  - **механизмы TK\*** сильны только на правках кода: на правке промпта rerun даёт лишь «differs from the start»;
  - **факт «ни разу не истинно»** может указать на законную охрану для другого случая.
- Внесено в `docs/REPORT-1106.md` (раздел «Где мерка и механизмы не общие»).

## Код

<!-- LAB-1103.md:2591–2696 -->
**Код пробы** (приписано 10.11). Из кода убран в a13b543: в develop осталась одна база. Последний коммит с этим кодом — 951bc3b (`git show 951bc3b:ФАЙЛ`); номера строк в листинге — по нему.

`--ticket-passed` (TKP)

```python
# nrhsi/editor/gate.py:462-476
def _cond_probes(changed):
    """6.11 --ticket-passed: {"файл:строка": проба} — значение самого изменённого условия (если вычислимо без побочных эффектов)."""
    import ast
    out = {}
    for rel, (lines, text) in changed.items():
        for ln in lines:
            if text[ln - 1].strip().startswith(("if ", "elif ", "while ")):
                c = _cond_of(text, ln)
                try:
                    ok = c and _safe(ast.parse(c, mode="eval"))
                except SyntaxError:
                    ok = False
                if ok:
                    out[f"{rel}:{ln}"] = f"bool({c})"
    return out

# nrhsi/editor/gate.py:479-515
def _fired_fact(changed, cov, hide=frozenset(), cprobe=None):
    """6.11 --ticket-passed: изменённые условия, тело которых выполнялось в прогоне (до расхождения) и которые истинны на последнем
    выполнении (если это вычислимо), и `return <выражение>`, вернувшие True, — до двух, со значениями операндов."""
    res = []
    vals = cov.get("__val__") or {}
    ret = cov.get("__ret__") or {}
    tm = lambda n: f"{n} time" + ("" if n == 1 else "s")
    for rel, (lines, text) in sorted(changed.items()):
        hits = {int(k): v for k, v in (cov.get(rel) or {}).items()}
        rets = {int(k): v for k, v in (ret.get(rel) or {}).items()}
        for ln in lines:
            src = text[ln - 1].strip()
            code = src.split("  #")[0].split(" # ")[0].strip()
            if hits.get(ln) and code.startswith("return ") and code[7:].strip() not in ("False", "True", "None") \
                    and (rets.get(ln) or {}).get("True"):
                res.append((rets[ln]["True"], f"your `{src[:80]}` at src/{rel}:{ln} returned True {tm(rets[ln]['True'])}"))
                continue
            if not hits.get(ln) or not src.startswith(("if ", "elif ", "while ")):
                continue
            pv = ((vals.get(f"{rel}:{ln}") or {}).get("vals") or {}).get((cprobe or {}).get(f"{rel}:{ln}"))
            if pv == "False":   # на последнем выполнении ложно: это охрана, не то, что сработало
                continue
            end = next((k for k in range(ln, min(ln + 8, len(text)) + 1) if text[k - 1].split("#")[0].rstrip().endswith(":")), None)
            if end is None:
                continue
            ind = len(text[ln - 1]) - len(text[ln - 1].lstrip())
            body = next((k for k in range(end + 1, len(text) + 1) if text[k - 1].strip() and not text[k - 1].strip().startswith("#")), None)
            if not body or len(text[body - 1]) - len(text[body - 1].lstrip()) <= ind or not hits.get(body):
                continue
            v = vals.get(f"{rel}:{ln}") or {}
            # пробы элемента all/any выбраны под «ни разу не истинно»; у сработавшего условия они не о том
            ops = {e: x for e, x in (v.get("vals") or {}).items() if e not in hide and e not in _SYN and not _is_err(x)}
            res.append((hits[body], f"your `{src[:80]}` at src/{rel}:{ln} was true {tm(hits[body])}"
                       + (f" (at its last run, before model call {v['call'] + 1}: " + ", ".join(f"`{e}` = {x}" for e, x in ops.items()) + ")"
                          if ops else "")))
    # то, после чего прогон разошёлся, обычно сработало раз-другой; охраны вроде `if history:` — на каждом шаге
    return [t for _, t in sorted(res, key=lambda x: x[0])[:2]]

# nrhsi/editor/gate.py:518-538
def passed_fact(run, changed, watch, hide):
    """6.11 --ticket-passed: первый удачный в логе прогон (не из тикета), который с кодом правки (тексты — как в виде) идёт иначе:
    где он расходится и какие изменённые условия в нём сработали. None — такого нет или промпт отличается от лога."""
    ch, passed, prompt = changed_runs(run.last_rerun or "", run.root)
    hit = sorted((ch & passed) - set(C.TICKET["runs"]))
    if prompt or not hit or not changed:
        return None
    r = hit[0]
    src = _old_texts_src(run) if _texts_differ(run) else f"{run.root}/src"
    cp = _cond_probes(changed)
    w = {k: list(v) if isinstance(v, list) else v for k, v in (watch or {}).items()}
    for where, pr in cp.items():
        w.setdefault(where, []).append(pr)
    div, cov = _replay(src, run.root, [r], cover=True, watch=w or None)
    d = div.get(str(r))
    if not d or d["kind"] == "crash":
        return None
    f = _fired_fact(changed, cov.get(str(r)) or {}, hide | set(cp.values()), cp)
    more = f" (of {len(hit)} such runs: {', '.join(map(str, hit[:8]))}{' …' if len(hit) > 8 else ''})" if len(hit) > 1 else ""
    return (f"Run {r} passed in the log{more}; with your code it goes differently from model call {d['call']} on"
            + (": " + "; ".join(f) if f else "") + ".")

# nrhsi/editor/gate.py:693-699
if getattr(C, "TICKET_PASSED", False):   # 6.11: факт о первом задетом удачном прогоне
    if watch is None:
        changed = changed or _changed_lines(run)
        watch = _watch(changed)
    pf = passed_fact(run, changed, watch or None, hide)
    if pf:
        lines.append(pf)

# nrhsi/editor/gate.py:616-617
if getattr(C, "TICKET_PASSED", False):
    watch["__shape2__"] = True

# editor/rerun.py:274
shape2 = shape and bool((watch or {}).get("__shape2__"))   # 6.11 --ticket-passed: и у элементов коротких списков

# editor/rerun.py:301-302
elif shape2 and isinstance(v, (list, tuple)) and v:   # короткий список — каждый элемент со своей формой
    vals[e] = "[" + ", ".join(rv(x, 60) for x in v) + "]"
```


## Связанные записи

- [6.11](../days/1106.md): «Мерка: пары по месту расхождения»
