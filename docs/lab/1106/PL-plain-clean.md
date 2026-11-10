# PL — голые виды + `--clean`

[Указатель проб](../INDEX.md) · хронология: [6.11](../days/1106.md) · как устроено — [README](../README.md)

<!-- LAB-1103.md:2992–3013 -->
## 6.11, 17:34 — голые виды (решение автора) и серия PL

- **Автор:** «README сделай минимальным, таким, что не соврёт скорее всего: где src, где logs, формат, reruns. Комментарии можно убрать вообще, хороший код говорит сам за себя».
- **`python3 -m nrhsi.plain ВИД ВЫХОД`** (сначала `editor/plain_view.py`).
  - Копия вида: `src/*.py` без комментариев и докстрингов (tokenize + ast). Тело, оставшееся пустым, получает `pass`. Пустых строк подряд — не больше двух.
  - Проверка: ast без докстрингов совпадает с исходным. Карта строк — в `ВЫХОД.linemap.json`, вне вида.
  - README — минимальный: что в `src/` (одной строкой на файл, без описания поведения), `bridge.py` не трогать, формат `logs/`. Строка «Read the failed runs…» оставлена: у писателя её вырезает work.py.
  - Шесть видов десяти входов — `runs/plain_1106/{alf_n4, app_r1, app_r4, alf_r1, alf_r4chk, app_n2}`. Строк в harness.py: 226→177, 191→149, 241→189, 124→115, 124→115, 121→110.
  - **Повтор на голом src:** на всех шести видах «all N runs: no changes»; app_r4 — также с `--old` на исходном src (ответы хуков те же).
- **Входы `runs/plain_1106/in/`** (`editor/plain_inputs.py`):
  - номера строк src/*.py пересчитаны по карте;
  - убраны две фразы о комментариях: 01 «The docstring at src/harness.py:13-17 says…», 04 «The comment at :187-190 says…»;
  - сверка: процитированные строки кода те же, что в v2; разница только в удалённых комментариях.
- **Шум, исправлен для всех сессий начиная с этой минуты.** Убирает случайное значение, своё в каждой сессии, поэтому TKK и CL не смещает.
  - Время файлов в копии было закреплено ещё 4.11 (b5b7ab7). Днём в списке идей я назвал это несделанным — ошибка, не сверился с кодом.
  - Протекал `..`: профиль песочницы и временная копия тикета писались в `work/` после закрепления. Теперь `make_profile` возвращает время `work/`, а копия тикета лежит в `HERE/`. Проверено заглушкой: время `work/` на старте сессии — 1.11 03:00.
  - `PYTHONHASHSEED=0` в песочнице (researcher/sandbox.py), так что порядок печати `set` одинаков.
- **Серия PL** (30 = 10 входов × s1–s3): флаги TKD, голые виды, новые входы, тикеты `tickets_1106` (без keep). Встала в очередь после CL.
  - Пар с TKD нет: файлы другие с первого чтения.
  - Мерка: вердикты против TKD 5/4/4/17 (SD суммы ≈ 0,64 на 10, так что малую разницу не увидим). Процесс: bash на чтение src до первой правки; правки, опирающиеся на мёртвый код как на живой (01: `output_text(content)`).
  - **Ожидание:** чтение короче; вердикты в пределах шума.

*Из записи «6.11, 18:08 — разбор «отложенного» с автором; `--clean` и PL как чистая база» (LAB-1103.md; заголовок и остальное — в [6.11](../days/1106.md)):*

<!-- LAB-1103.md:3032–3043 -->
- **Ответ — чистая база до следующих сравнений.** `--clean` (cli, prompt, phase, tools) собирает исправления известных изъянов, без новых гипотез:
  - строка проверки CL — одна, фактом про авто-проверку;
  - «for a few turns» → «3 turns remain without bash: edits are still applied and checked after each one»;
  - заметка о конце bash — факт («Edits are still applied and checked after each one; 3 turns remain»), без «settled on… then call finish»;
  - отказ bash без «Use edit, then call finish»;
  - «Call finish when you are done» убрано из How to work и из конца первого сообщения; остаётся описание finish();
  - **повтор той же команды — обычный вывод**, как в shell; счёт `repeats` остаётся.
    - Было: «This is the same command as tool call N… so the result is the same» и первые 600 знаков.
    - После применённой правки `seen` очищается, так что rerun после правки не перехватывался. Но ответ малоговорящий, и он беднее исходного вывода.
    - В wvar_1104 такой ответ был 86 раз: логи 28, rerun 19, src 11, прочее 28. Типично — повтор команды, давшей ошибку. 04_SW1 после повтора `rerun.py 7` решил, что «the rerun detail command seems to need an argument».
- **Проверка:** без `--clean` `--dry` байт в байт как до правки (база, `--check-auto-only`, `--checked`; worktree HEAD). С `--clean` — строки как выше. Отказ и заметка конца проверены вызовом `bash_call` и `enter_final` на заглушке. pyflakes 0.
- **PL = голые виды + `--clean`** (30 заданий, ещё не начаты, флаг дописан). Сравнение с TKD — пачкой, это смена базы. Следующие сравнения — от PL, по одному фактору.

<!-- LAB-1103.md:3108–3120 -->
## 6.11, 18:16 — ответ на повтор команды: поправка автора

- **Автор:** «проблема в том, что он не говорит модели "не делай". Это просто странный факт». Мой вариант в `--clean` (обычный вывод, как в shell) был ошибкой: он вообще убирал сигнал.
- **Разбор:** 10 случайных из 86 повторов в wvar_1104, scratchpad `later/rep10.txt`.
  - Что повторяли: ошибку 50, пустой вывод 10, обычный вывод 26. Повтор — почти всегда надежда, что команда, давшая ошибку или пустоту, выдаст другое.
  - Реакции:
    - 07_W15a и 09_ST_s2 — снова тот же падающий скрипт через ход;
    - 08_TKC и 08_TKD_s1 — второй `cat bridge.py` (No such file), дальше идут, будто ничего не было;
    - 09_AQ — тот же `rerun.py --bench app` с хвостом `; echo "EXIT: $?"`, то есть обошёл перехват;
    - 08_TKV_s3 и 08_TKP_s3 — законное перечитывание `src/hooks.py` через 18 ходов; ответ дал 600 знаков, и правка пошла по обрезку.
- **Теперь в `--clean`:** «This command was already run at tool call N, and no file has changed since, so it prints the same as there (repeated below). Running it again tells you nothing new: change the command, or go on from this output.» — и прежний вывод целиком. Вызов bash тратится, `repeats` считается.
- **Проверка:** `bash_call` на заглушке (повтор `cat  bridge.py` с лишним пробелом совпадает по ключу). pyflakes 0. Без `--clean` ответ прежний. Мерка в PL: доля повторов, после которых следующий вызов — снова та же или почти та же команда.

<!-- LAB-1103.md:3258–3273 -->
## 6.11, 23:39 — PL прочитан (30): голые виды + `--clean`

- **Вердикты:**
  - s1: 00 B (обрыв и в удачном 1), 01 B (`code in [-3:]`, задеты 3), 02 V (`pop` истории — второй повтор исполняется), 03 x (`if episode.end is None: continue` — повтор молча пропускается без предупреждения), 04 x (мёртвое), 05 x (убран answer у вопроса), 06 x (`ctx["action"]` — ключа нет), 07 V (ответ без вызова отбрасывается, без сообщения), 08 x (правок нет), 09 x (`answer=23`);
  - s2: 00 B (обрыв, задеты 23), 01 B, 02 x (мёртвое), 03 x (условие «код = код и вывод = код» никогда не истинно), 04 B, 05 P (в пример добавлена ветка для задачи-действия), 06 V (блок недопустимого, задеты 15), 07 x (обрыв эпизода), 08 B (задеты 3), 09 x (правок нет);
  - s3: 00 x, 01 B (окно 2), 02 V (повтор исполняется), 03 x и 04 x (правок нет), 05 P (строка в инструкции), 06 x (`ctx["raw"]`), 07 x (обрыв), 08 B (skills с целью, широкая), 09 x (хук `on_observation` харнесс не вызывает).
- **Итог 4/2/8/16 против TKD 5/4/4/17.** Сумма по seed: PL 2,5 / 2,5 / 2,0, TKD 1,75 / 3,5 / 2,75; разность +0,75 / −1,0 / −0,75 — шум. B вдвое больше, V и P меньше; по одной серии без пар это не отличить от перетасовки.
- **Процесс** против TKD:
  - первая правка на bash 21 против 24 (медиана); bash по src/ до правки 5 против 6;
  - `finish` 19 против 16;
  - отказов bash после конца 31 против 21 — новая заметка «edits are still applied… 3 turns remain» от попыток bash не удерживает;
  - повторов команды 1 против 7;
  - ручной rerun 14% против 11%; чтение tests/ 23% против 20%.
- **Ловушка `output_text` в 01:** в TKD 01 s1 писатель построил правку на ней (x). В PL ни одна из трёх сессий 01 её не взяла (все B). Слабый сигнал в пользу голых видов, одна точка.
- **Вывод:** чистая база не хуже и не лучше по вердиктам (*средняя*). Процесс чуть короче до правки. Дальше сравнения — от PL по одному фактору. Первая в очереди проба по плану — PL без «trust your colleague initially».

## Код

<!-- LAB-1103.md:3052–3107 -->
**Код пробы** (приписано 10.11). Из кода убран в a13b543: в develop осталась одна база. Последний коммит с этим кодом — 951bc3b (`git show 951bc3b:ФАЙЛ`); номера строк в листинге — по нему.

`--clean` (PL): тексты базы остались (`prompt.SYSTEM`, `phase.enter_final`, `tools.bash_call`); убраны прежние тексты, которые они заменили

```python
# nrhsi/editor/prompt.py:52-55
- Read the part of src/ a change touches before you edit it, and keep intact what the rest of the harness relies on: README.md and the comments at the top of the code describe how the parts fit together.
- Check each change: run python3 tests/smoke.py, and read the changed lines together with the code that calls or uses them.
- bash can be called BASH_LIMIT times; after that only edit and finish remain, for a few turns, and the session ends.
- Call finish when you are done."""

# nrhsi/editor/prompt.py:99
LIMIT_LINE = "- bash can be called BASH_LIMIT times; after that only edit and finish remain, for a few turns, and the session ends."

# nrhsi/editor/cli.py:189-197
if a.clean:   # 6.11: «a few turns» — число; «Call finish when you are done» — один раз, в описании finish
    lim = P.fill(P.LIMIT_LINE)
    assert lim in esys and esys.count("\n- Call finish when you are done.") == 1
    esys = esys.replace(lim, P.fill(P.CLEAN_LIMIT_LINE)).replace("\n- Call finish when you are done.", "")
    assert first.count(" Call finish when you are done.") == 1
    first = first.replace(" Call finish when you are done.", "")
    old = ": README.md and the comments at the top of the code describe how the parts fit together."
    assert esys.count(old) == 1   # 10.11: в голых видах комментариев нет, README не описывает устройство
    esys = esys.replace(old, ".")

# nrhsi/editor/phase.py:11-17
tail = ("Edits can no longer be checked, so they are not applied: call finish." if run.role == "editor" and C.CHECKED else
        f"Edits are still applied and checked after each one; {C.FINAL_TURNS} turns remain, then the session ends."
        if run.role == "editor" and C.CLEAN else
        "Make the edits you have settled on with edit now (several edit calls in one reply are fine), then "
        "call finish." if run.role == "editor" else
        "Record the proposals you have settled on with propose now (several propose calls in one reply are "
        "fine), then call finish.")

# nrhsi/editor/tools.py:25-27
if C.CLEAN:
    return "Error: bash is no longer available; this command was not run.", False
return f"Error: bash is no longer available; this command was not run. Use {run.act}, then call finish.", False

# nrhsi/editor/tools.py:47-59
if key in run.seen and C.CLEAN:   # 6.11, автор: повтор — сказать, что нового не будет, и что делать; вывод целиком
    st["repeats"] += 1
    res["repeat"] = True
    return (f"This command was already run at tool call {run.seen[key][0]}, and no file has changed since, so it "
            f"prints the same as there (repeated below). Running it again tells you nothing new: change the "
            f"command, or go on from this output.\n{run.seen[key][1]}"), False
elif key in run.seen:
    st["repeats"] += 1
    res["repeat"] = True
    old = run.seen[key][1]
    head = old if len(old) <= 600 else old[:600] + f"\n[... {len(old)} characters in all]"
    return (f"This is the same command as tool call {run.seen[key][0]}, and the files have not changed since, "
            f"so the result is the same:\n{head}"), False
```


## Связанные записи

- [6.11](../days/1106.md): «6.11, 17:05 — сверка промпта…»: изъяны, которые собрал `--clean`
- [6.11](../days/1106.md): «6.11, 18:08 — разбор «отложенного»…»: поправки автора, с которых начат `--clean`
- [6.11](../days/1106.md): «6.11, 17:50 — чистка комментариев в каждом узле дерева»
- [rp_1106…](RP-repeat-answer.md): проба ответа на повтор (выбор ответа для PL)
