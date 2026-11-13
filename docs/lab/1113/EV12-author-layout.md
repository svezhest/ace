# EV12 — оценщик: блок прогона по раскладке автора, без таблицы прогонов

[Указатель проб](../INDEX.md) · хронология: [13.11](../days/1113.md) · прежняя проба: [EV11](EV11-sparse-steps.md)

- **Повод.** Автор (13.11): «а нужна ли нам таблица RUNS вообще? модель же делает вывод по блокам. что ей вообще дадут
  прогоны которые не поменялись?» и раскладка блока: «Run N: Previously OK/NOT OK, A chars, B steps, now diverges at
  A' chars, B' steps. Context: Step S1 … <-- Divergence point / Diff / Note: the previous run continued with the
  followings steps. They might be not the same now. Step S10 …».
- **Что поменялось** (`ev_input.run_blocks_v2`, `_chars`, промпт `runs_v2`; `ev_judge.py --v2`). От EV11:
  - нет раздела «The recorded runs» (таблица `tests/runs.py`) и ряда версий; сводка перепрогона — одной фразой
    (сколько прогонов, какие идут иначе);
  - заголовок: «### Run 9: previously NOT OK (task failed), 92011 chars, 55 steps; now diverges at 39169 chars, after
    step 19.» — знаки всех сообщений прогона (всего и до вызова K), шаги — вызовы модели;
  - «Context:» — три случайных шага EV11 с пометкой «(steps 6, 13 are picked at random from earlier in the run; then
    steps 14-19 in a row)» и шаги K−6…K−1; шаг подписан «Step k» (было «model call k»);
  - «<-- Divergence point», «Diff: <что харнесс делал в логе и что делает теперь>» (текст `rerun.event_text`, прежний);
  - «Note: the previous run continued with the following steps. They might not be the same now.» и шаги K…K+2;
  - форма ответа — «Run N, step K: …», «Where: run N, step K: …» (`runs_v2`; разбор `Where` принимает и call, и step).
- **Цена входа.** 40 правок, в среднем 18,9 тыс. знаков (EV11 — 20,7 тыс.: таблица прогонов ушла).
- **Набор и база.** t1 (21), 08 (19), слепая разметка. База — EV11 (тот же выбор шагов, прежняя раскладка) и окно 6
  из EV10 (32 из 40). Исход прогона вернулся в заголовок — сравнение с EV6a (36 из 40) тоже имеет смысл.
- **Ожидание (13.11, 14:31 по `date`, до запуска).**
  - Исход «previously OK» в заголовке снова даёт опору: перечитывания в решённых run 14, 17, 18 (5 плохих, потерянных в
    окне 6) — снова «a step that was fine» → «Failed», как в EV6a. Жду пойманных на t1 9–11.
  - Знаки и шаги в заголовке на вердикт, скорее всего, не влияют.
  - Довод «прогон провален — значит, шаг не нормальный» может вернуться (E13 на 08 в EV7).
- **Запуск.** `runs/ev_1112/run_ev12.sh` — после EV11 → `t1_plain27_v2.jsonl`, `08_plain27_v2.jsonl`.
