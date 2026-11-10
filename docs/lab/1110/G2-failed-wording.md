# G2 — читается ли Failed по тикету как провал

[Указатель проб](../INDEX.md) · хронология: [10.11](../days/1110.md) · как устроено — [README](../README.md)

<!-- LAB-1110.md:132–158 -->
### Проба G2: читается ли Failed по тикету как провал

- **Гипотеза.** Строка «Failed: run 40 goes exactly as in the log, to the end: this edit changes nothing in it» делит
  фразу с целью для удачного прогона («still goes exactly as in the log») и читается как успех (сессия py39 T17 и 1 из 4
  развилок: «run 40 goes exactly as the log — good»).
- **Изменение (в развилке, `--sub` по ответу проверки):** «Failed: run 40 goes exactly as in the log, to the end: this
  edit changes nothing in it» → «Failed: this edit has no effect in run 40, the run the observation is about».
- **Мерка.** Два состояния сразу после первой проверенной правки (`fk/h_t/logs/t_r0.jsonl` — без значений условия,
  `t_r1.jsonl` — со значениями), следующий ход 10 раз на плечо. Глазами: «провал понят» (говорит, что правка не подействовала
  на прогон 40, и идёт чинить) / «прочитано как успех» (good, unchanged, finish) / «о другом».
- **Ожидание (до замера).** База: «как успех» 3–4 из 10 в каждом состоянии; новая строка: ≤ 1 из 10.
- **Итог G2, 01:56 по `date`** (`fk/g2_*.txt`, 40 ответов прочитаны глазами по первой фразе и вызову).
  - Состояние `t_r0` негодно: правка там — первый шаг плана (запись истории в `harness.py`), в обоих плечах 10 из 10
    продолжают план и строку проверки не обсуждают.
  - Состояние `t_r1` (правка «это действие уже было», в прогоне 40 условие ни разу не истинно, значения показаны):

    | | провал понят | как успех или путаница |
    |---|---|---|
    | прежняя строка | 5 | 5: «my guard correctly does nothing to it», «the log is preserved exactly», «the checker is conservative and correct», «the rerun test passes (no changes)», «the log's model keeps repeating regardless of the hint» |
    | новая строка | 10 | 0 |

    С новой строкой сразу правят 4 из 10 (с прежней 1), остальные идут смотреть `memory` и шаги прогона 40.
  - Ожидание (3–4 → ≤ 1) сбылось: 5 → 0.
- **Вывод.** Формулировка Failed по тикету чинится одной строкой. *Средняя* (одно состояние, n = 10; верна ли следующая
  правка — не мерил). Строка в `gate.py` заменена: «Failed: this edit has no effect in run N, the run the observation is about».
- **Не проверено:** состояния без значений условия; вход про тексты (`change_expected: prompt`); App.

## Связанные записи

- [G1–G5 (код)](G1-G5-code.md): код и запуск G1–G5
