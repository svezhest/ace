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
