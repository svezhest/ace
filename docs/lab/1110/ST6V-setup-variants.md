# ST6V — три варианта постановки: первый ход и первые три вызова (тикет 10.11, шаг 6)

[Указатель проб](../INDEX.md) · хронология: [10.11](../days/1110.md) · тикет: [TICKET-1110-writer](../../TICKET-1110-writer.md)

- **Гипотеза.** База отвечает на вопросы «что сделать, на чём видно, что должно остаться, что значит готово, что
  стоит bash» в четырёх местах и называет цель трижды ([ST5](ST5-setup-inventory.md)). По [ST6](ST6-first-turn-base.md)
  пересказ на прямой вопрос в целом верен, а расходится с замыслом в четырёх местах: общая цель первой строкой
  (73 из 80), отступление к общей цели на входе без названной починки (09: 8 из 20), ожидание «прогон пройдёт»
  (19 из 80), путаница ролей прогонов (5 из 40). Если собрать ответы одним блоком в конце первого сообщения и
  назвать одну цель, эти четыре места сдвинутся.
- **Пробовали ли.** Строку цели одну — G1 (не установлено); здесь она в одиночку не меняется: вариант A меняет
  цель вместе с блоком и «готово», вариант B — блок без цели. Якорь цели строкой (W2, W10), план, пример — закрыто,
  здесь их нет. Длинный блок фактов в ответе проверки (TKC, TKR) не читался; здесь блок не длиннее заменяемого
  текста плюс 100–500 знаков. Довод, почему это не перепрогон G1: меняется не строка, а место и состав ответа на
  «что значит готово», и мерка другая — пересказ и первые вызовы на четырёх входах, а не первая правка на одном.
- **Изменение — только в развилке** (`probes/1110/s6/variants.py`; база и код писателя не тронуты).
  - **B — блок, цель прежняя.** Хвост первого сообщения («Change expected… Change src/ so that the agent fails fewer
    tasks.») заменён блоком «What is asked»; в системном промпте фраза 2 описи («Each observation… is a candidate»)
    заменена на «The first message holds one observation and, after it, what is asked of the change.» Меняет фразы
    2, 11, 12, 13, 14 описи: одна точка входа вместо четырёх, слово «goal» у keep убрано, сказано, что такое повтор.
  - **A — B + одна цель и «готово».** Системный абзац цели: «Your task: make the change to src/ that the observation
    in the first message calls for, so that the harness handles the situation it describes. … The same harness runs
    on every task the agent gets: what you change acts in every run, not only in the runs the observation is about.»
    В блоке — строка «Done». Меняет ещё 1 и 5: цель одна, указание «aim for changes that help on tasks in general»
    заменено фактом. Меняет цель писателя — вопрос 3 тикета; ответ автора «да» передан через сессию itmo-42,
    в этой сессии не подтверждён; проба обратима.
  - **C — A + бюджет в том же блоке.** Строка о 25 вызовах bash и трёх ходах после них перенесена из «How to work»
    в блок; из строки о проверках убрано «this uses no bash calls» (оно теперь в блоке). Меняет ещё 7 и 9: место,
    не содержание.

  Блок варианта A на входе 08 (control, keep):
  ```
## What is asked
A change to src/ after which the harness handles what this observation describes.
- Where it shows: run 40. Replayed on your src/ (the model's replies are taken from the log), the harness code should act differently there, not only the texts the model reads.
- What should stay: run 28, which passed. Replayed on your src/, it should go as in its log.
- Both replays run after each edit and come with the edit's answer.
- Done: in run 40 the harness handles what the observation describes, and run 28 goes as in its log.
  ```
  Блок варианта C на входе 05 (prompt, keep нет):
  ```
## What is asked
A change to src/ after which the harness handles what this observation describes.
- Where it shows: runs 6 and 12. Replayed on your src/ (the model's replies are taken from the log), the texts the model reads there should change.
- The replay runs after each edit and comes with the edit's answer.
- Done: in runs 6 and 12 the harness handles what the observation describes.
- bash can be called 25 times. Edits and the checks after them use no bash calls. After the 25th bash call 3 turns remain without bash; edits are still applied and checked in them, and then the session ends.
  ```
  Блок варианта B на входе 09 (any, keep нет):
  ```
## What is asked
A change to src/ so that the agent fails fewer tasks; this observation is where to start.
- Where it shows: run 8. Replayed on your src/ (the model's replies are taken from the log), it should go differently, through the texts the model reads or through the harness code.
- The replay runs after each edit and comes with the edit's answer.
  ```
  Системный абзац B: «Your goal: change src/ so that the agent fails fewer tasks. The first message holds one observation and, after it, what is asked of the change. An observation may also be inaccurate, or point to something the harness cannot change; what it says about src/ you can check by reading src/. The same harness runs on every task the agent gets, so aim for changes that help on tasks in general. A change may be to a prompt or to the code.»

  Системный абзац A и C: «Your task: make the change to src/ that the observation in the first message calls for, so that the harness handles the situation it describes. An observation may also be inaccurate, or point to something the harness cannot change; what it says about src/ you can check by reading src/. The same harness runs on every task the agent gets: what you change acts in every run, not only in the runs the observation is about. A change may be to a prompt or to the code.»
- **Два вопроса общности.** Наводка на задачу входа: нет, в блок идут только номера прогонов и тип из тикета, как в
  базе. Предполагает ли устройство бенчмарка: нет; «replayed on your src/ (the model's replies are taken from the
  log)» — факт о `tests/rerun.py`, одинаковый для обоих бенчей (README обоих).
- **Мерка.** Те же входы 05, 06, 08, 09, те же seed (5000–5019), та же разметка, что в ST6: первый ход на thinking
  (20), ответ на тот же вопрос на default (20). Плюс первые три хода настоящим харнессом на default, 10 на клетку,
  база и три варианта на одних seed (`probes/1110/s6/roll3.py`).
- **Ожидание (до замера, 20:29 по `date`).** База → вариант, из 80 (4 входа × 20), если не сказано иное.
  1. Пункт 1 начинается с общей цели: 73 → B не меньше 60; A и C не больше 10. (Пересказ повторяет текст: это
     проверка, что изменение увидено, а не эффект.)
  2. На входе 09 пункт 1 называет содержание наблюдения: 12 из 20 → A и C не меньше 17; B — как база (10–14).
  3. Пункт 2 ждёт, что прогон «пройдёт»: 19 → не больше 8 у всех трёх (слова о повторе есть во всех).
  4. Путаница ролей прогонов (06, 08): 5 из 40 → не больше 2 у всех трёх.
  5. thinking без вопроса: «готово» или проверка названы 0 → не больше 5 у всех трёх (сдвига не жду); keep 3 из 40 →
     не больше 6.
  6. Первые три хода (default, 40 прокатов на плечо): первый вызов `cat README.md` у всех плеч; запуск
     `tests/rerun.py` или `tests/runs.py` в первых трёх ходах — не больше 3 из 40 в любом плече; состав прочитанных
     файлов тот же. Сдвига не жду.
  - Порог: принимается только сдвиг масштаба G2. Если сбудутся 3 и 4, а 6 не сдвинется (как жду) — вариант меняет
    пересказ, но не дело первого хода; тогда судить его надо в точках решения (шаг 7) и на полных сессиях (шаг 10),
    а не здесь. Если не сдвинутся и 3, и 4 — блок чтения не чинит, вариант снят.
- **Итог.** (дописывается ниже)
