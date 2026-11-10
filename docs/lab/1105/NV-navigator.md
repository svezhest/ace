# NV — точный навигатор, ступень 1 (`--navigator`)

[Указатель проб](../INDEX.md) · хронология: [5.11](../days/1105.md) · как устроено — [README](../README.md)

<!-- LAB-1103.md:1330–1342 -->
## Проба NV: точный навигатор, ступень 1 — пример в промпте (05.11)
- Коммит 8c01cde: `--navigator` — перед «# How to work» раздел «Example: finding what a change needs (another repository)». Выдуманный репозиторий: экспорт CSV теряет последнюю строку. Тема нарочно далека от наблюдений (первый вариант был про счётчик повторов — заменил до запуска: слишком близко к нашим повторам). Форма без пояснений:
  1. grep -n по именам из наблюдения;
  2. sed -n по найденной функции;
  3. sed -n по вспомогательной;
  4. sed -n по месту вызова;
  5. grep по логу с cut/head.
- Плечо NV: W1 (`--rerun`, 25 bash) + `--navigator`, 10 наблюдений × seed 1. База — W1 seed 1 (не пары: промпт разный).
- Мерка процесса (scratchpad b1/nav.py), всё до первой правки: чтений файла целиком, прицельных команд (sed -n, grep -n…), тыс. символов вывода, bash.
  - База по 10 сессиям: W1 — 71 целиком, 58 прицельных, медиана 66K символов, 24.5 bash; HT — 63/57/56K/22.5; AC — 71/72/76.5K/23.5.
- Затем вердикты руками.
- Ожидание: чтений целиком заметно меньше, символов меньше, первая правка раньше; V не меньше, чем у W1 (2/10).

*Из записи «Проба IN: намерение в edit (05.11; пользователь: «это thinking снаружи =) …пробуй и документируй»)» (LAB-1103.md; заголовок и остальное — в [IN](IN-intent.md)):*

<!-- LAB-1103.md:1420–1439 -->
- **Итог NV, ступень 1** (10 сессий, seed 1):
  - Процесс до первой правки, NV против W1:
    - чтений файла целиком 54 против 71;
    - прицельных команд 74 против 58;
    - символов 61K против 66K (медиана);
    - bash до первой правки 17.5 против 24.5 (медиана).
  - Сдвиг есть, ритуал остался: 9 из 10 начинают с `cat README.md` и `cat src/harness.py` целиком. Сразу прицельно начал только 03_NV (`sed -n '140,175p'`).
  - Вердикты:
    - 00 x (обрыв на вызове 0);
    - 01 B ([-2]);
    - 02 x (обрыв на вызове 1 во всех прогонах);
    - 03 V (текст «already ran successfully. Re-running it will not change the result»);
    - 04 без правок;
    - 05 x (вопрос без answer);
    - 06 V;
    - 07 V (ответ без вызова не отдаётся задаче);
    - 08 x (тикет не задет);
    - 09 x (только answer=23: копия примера больше не падает NameError, но отдаёт чужой ответ).
  - Итого V3 B1 x6 против W1 V2 P2 B1 x5. По вердиктам в пределах шума (одна сессия на наблюдение).
  - Вывод: пример сдвигает форму чтения (меньше целиком, раньше правка), но не отменяет ритуал. Ступень 2 навигатора — подумать: пример ещё и того, как не читать (начать с места из наблюдения)?

## Код

<!-- LAB-1103.md:1343–1377 -->
**Код пробы** (приписано 10.11). Из кода убран в a13b543: в develop осталась одна база. Последний коммит с этим кодом — 951bc3b (`git show 951bc3b:ФАЙЛ`); номера строк в листинге — по нему.

`--navigator` (NV)

```python
# nrhsi/editor/prompt.py:141-161
NAV_EXAMPLE = """# Example: finding what a change needs (another repository)
Observation: "Exported reports lose their last row: write_rows() (src/export.py:40-52) stops one row early."

bash(command="grep -n 'write_rows\\|n_rows' src/*.py")
src/export.py:18:def n_rows(table):
src/export.py:40:def write_rows(out, table):
src/report.py:63:    write_rows(f, table)

bash(command="sed -n '36,56p' src/export.py")
def write_rows(out, table):
    for i in range(n_rows(table) - 1):
    ...

bash(command="sed -n '16,24p' src/export.py")
...

bash(command="sed -n '55,70p' src/report.py")
...

bash(command="grep -n 'rows' logs/run_4.jsonl | cut -c1-200 | head -5")
..."""

# nrhsi/editor/cli.py:180-182
if a.navigator:
    assert "\n# How to work\n" in esys
    esys = esys.replace("\n# How to work\n", "\n" + (P.NAV_EXAMPLE2 if a.nav_v == 2 else P.NAV_EXAMPLE) + "\n\n# How to work\n")
```


## Связанные записи

- [SW1, SNV](SW1-SNV-symptom-only.md): SNV — навигатор на входах «только симптом»
- [IO, AQ, NV2, TP, BR](IO-AQ-NV2-TP-BR.md): NV2 — навигатор, ступень 2
