# CL — строка проверки без двойной инструкции (`--check-auto-only`)

[Указатель проб](../INDEX.md) · хронология: [6.11](../days/1106.md) · как устроено — [README](../README.md)

*Из записи «TKK и CL (6.11, 15:43 по `date`)» (LAB-1103.md; заголовок и остальное — в [TKK](TKK-keep.md)):*

<!-- LAB-1103.md:2917 -->
- **CL — строка проверки без двойной инструкции** (`--check-auto-only`). «Check each change: run smoke and rerun…» плюс «they are run by themselves» заменено одной строкой: «Checks run by themselves… To look at one run in detail, run python3 tests/rerun.py N yourself». Мерка процессная: доля bash на ручной rerun и smoke и на чтение tests/ (в TK* 15 + 7 + 14 %), bash первой правки.

<!-- LAB-1103.md:3209–3225 -->
## 6.11, 23:33 — CL прочитан (10)

- Вердикты s1:
  - 00 x — мёртвое условие; обрывает 2 прогона, в том числе удачный 13;
  - 01 B — задеты удачные 8 и 20;
  - 02 V — снят `continue`;
  - 03 x — TypeError;
  - 04 B — 2 удачных;
  - 05 x — у примера с вопросом убран answer;
  - 06 V — блок действия не из списка, плюс правка системного промпта;
  - 07 V — ответ без вызова не отдаётся задаче;
  - 08 x — мёртвое; задеты удачные 21 и 27;
  - 09 x — `answer=23`.
- **Итог 3/0/2/5 против TKD s1 1/1/1/7.** Сумма 3,5 против 1,75, SD разности на одном seed ≈ 0,9 — в пределах шума. Пар нет: промпт другой со старта.
- **Процесс** (главная мерка CL) не сдвинулся: ручной rerun 14% против 14%, smoke 3% против 2%, чтение tests/ 15% против 18%, первая правка на bash 22 против 24.
- **Вывод:** строка проверки без двойной инструкции нужна как исправление изъяна (она в `--clean`), но ручной rerun идёт не от неё. *Средняя* по процессу.

## Код

<!-- LAB-1103.md:2920–2941 -->
**Код пробы** (приписано 10.11). Из кода убран в a13b543: в develop осталась одна база. Последний коммит с этим кодом — 951bc3b (`git show 951bc3b:ФАЙЛ`); номера строк в листинге — по нему.

`--check-auto-only` (CL): строка CL осталась в базе (`prompt.SYSTEM`); убраны строки, которые она заменила

```python
# nrhsi/editor/prompt.py:97-98
CHECK_LINE = ("- Check each change: run python3 tests/smoke.py, and read the changed lines together with the code that "
              "calls or uses them.")

# nrhsi/editor/prompt.py:87-89
RERUN_CHECK_LINE = ("- Check each change: run python3 tests/smoke.py and python3 tests/rerun.py (see README.md), and read "
                    "the changed lines together with the code that calls or uses them. If python3 tests/rerun.py shows "
                    "no changes in the runs an observation is about, your change may have missed.")

# nrhsi/editor/cli.py:160-163
if a.check_auto_only:   # 6.11 CL: строка проверки — факт про авто-проверку, без «run smoke and rerun»
    assert chk == P.RERUN_CHECK_LINE and a.rerun and not a.rerun_tool, "--check-auto-only needs --rerun --auto-check"
    esys = esys.replace(chk + add, P.CHECK_AUTO_ONLY_LINE)
    assert P.CHECK_AUTO_ONLY_LINE in esys
```


## Связанные записи

- [6.11](../days/1106.md): «Ещё три места промпта писателя»: откуда CL
- [TKK](TKK-keep.md): строка «Очередь: TKK … CL …»
