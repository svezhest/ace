# EV19 — оценщик промпта: детали задачи и в примерах

[Указатель проб](../INDEX.md) · тема: [оценщик](../../writer.evaluator.md) · повод: [EV17](EV17-writer-prompt-rules.md)

- **Повод.** В EV17 условие задачи наблюдения ушло в примеры «e.g.» («песня несёт album_id, а жанр и дата — у альбома»,
  «"played so far"»), и оценщик промпта такие правки принимает. Пропуски его на итогах EV15–EV17 по моей разметке: t4 ev s2,
  14 ev s3, 14 pr s1, t4 pr s1–s4 — 7.
- **Пробовали ли.** Нет: второй пункт оценщика с EV13 один и тот же — «no details of the particular task … (its names,
  values or the exact condition of that task)».
- **Что меняется.** Конец пункта: «…of that task), not even as an example.» Больше ничего. Скрипт `probes/1114/ev19.py`
  (ветка `feature/writer-evaluator`), вход как у `review.py` на итоговом src сессии; 27B `plain27`, T=0, один вызов.
- **Разметка (глазами, до запуска).**
  - Failed (8): t4 pr s1, s2, s3, s4 (s1 и s4 — мягко: «e.g., a genre, a date»), 14 pr s1, t4 ev s2, 14 ev s3, 14 nl s1.
  - Ok (11): 05 pr s1, 09 pr s1, t4 ev s1 (пример с заглушкой «<the task's condition>»), 14 ev s2, 04 ev s2, 06 ev s2,
    06 nl s1, 07 ev s2, 09 ev s1, 09 ev s2, 05 ev s2.
  - Спорно, вне счёта: 14 pr s4 («"so far" or "up to now"»).
  - Прежний оценщик на этих же итогах: 8 Failed — 1 (14 nl), 11 Ok — 11.
- **Ожидание (14.11, 16:33 по `date`, до запуска).** Новый ловит не меньше 6 из 8 Failed; из 11 Ok не меньше 9 остаются
  Ok. Риск: перестрахуется на примерах вообще — 09 («e.g. num_playlists» — это пример из самого промпта, не задачи), 05
  (примеры задач в промпте и были), 06 («only carry one object» можно принять за деталь задачи).
- **Запуск.** 14.11 16:34–16:50, `runs/evw_1113/ev19_plain27.jsonl`; стенд после — 9B.

## Итог (14.11, 16:52 по `date`)

- **Failed по разметке (8): поймано 2** — t4 pr s2, t4 pr s4. Пропущены t4 pr s1, s3, 14 pr s1, t4 ev s2, 14 ev s3 и
  **14 nl s1**, хотя прежний оценщик в самой сессии ставил ему Failed.
- **Ok по разметке (11): Ok 8.** Ложные Failed: 05 pr s1 («includes specific examples from the failed runs ("play a song",
  "mark this note item as done")… even as examples» — а это обычные примеры задач, как в самом промпте), t4 ev s1, 09 ev s1.
- **Ожидание не сбылось** (≥ 6 из 8 и ≥ 9 из 11): стало хуже прежнего (1 из 8 и 11 из 11) по Ok, по Failed — шум.
- **Обоснования.** Какой пример — «условие задачи», а какой — «общий», модель решает на вкус и одинаково уверенно в обе
  стороны: «album_id but not the album's genre» — «hypothetical example … does not contain specific names» (t4 pr s3);
  «"so far", "yesterday or today"» — «generic enough … illustrative of the *type* of constraint» (14 pr s1); «"play a
  song"» — «specific examples from the failed runs» (05). Добавка «not even as an example» сдвигает вердикт по
  примерам случайно, а не к разметке.
- **Вывод.** Не вливаю. Одной фразой пункта граница «пример = случай задачи» для 27B не задаётся.
- **Не пробовали.** Форму ответа: сначала выписать детали задачи из наблюдения (имена, значения, условие), потом сверять
  с ними каждую новую строку. Другую модель-оценщик. Больше одного прогона на вход (T=0, повтор бесполезен).

## EV19b — сначала выписать детали задачи

- **Что меняется.** Пункт прежний (без «not even as an example»). В форме ответа первым идёт: «First, the details of the
  particular task from the observation: its names, values and condition, one line each.» Дальше как было. Те же 20
  итогов, `EV19=b probes/1114/ev19.py` → `runs/evw_1113/ev19b_plain27.jsonl`.
- **Ожидание (14.11, 16:51 по `date`, до запуска).** Выписанный список даёт модели, с чем сверять: Failed поймано не
  меньше 5 из 8, Ok не меньше 10 из 11. Риск: модель выпишет детали и всё равно назовёт пример «generic» — тогда граница
  не в том, видит ли она детали, а в том, как она понимает «общий».
