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
- **Запуск.** `bash probes/1110/s6/run_variants.sh <scratch>`: первый ход 20:29–20:38 по `date` (480 ответов, ошибок
  нет), прокаты на три хода 20:38–21:14 (160 прокатов; 36 минут вместо ожидавшихся 12). Данные —
  `runs/fk_1110/s6/{0,A,B,C}/`.
- **Итог, 21:16 по `date`.** Глазами прочитан пункт 2 («как узнаю, что сделано») всех 240 ответов на default и
  пункт 1 на входе 09; первые ходы прокатов — по командам. Рассуждения thinking у вариантов глазами не читал,
  только счёт слов.

  **default, ответ на вопрос (сумма по четырём входам, из 80; у ролей — из 40):**

  | что | база | B | A | C |
  |---|---|---|---|---|
  | пункт 1 начинается с «fails fewer tasks» | 73 | 75 | 0 | 0 |
  | на входе 09 пункт 1 называет содержание наблюдения (из 20) | 12 | 19 | 20 | 20 |
  | пункт 2 ждёт, что повтор покажет успех прогона или иное поведение модели | 19 | ≈45 | ≈22 | ≈22 |
  | — из них на входе 05 (из 20) | 8 | 19 | 16 | 14 |
  | путает, какой прогон меняется, а какой остаётся (06, 08) | 5 | 0 | 0 | 0 |
  | вместе с ответом или вместо него — вызов инструмента | 11 | 12 | 27 | 56 |

  **thinking без вопроса (счёт слов, из 80; keep из 40):** проверка или повтор названы 0 / 3 / 3 / 3; keep 3 / 5 / 2 / 4.

  **Первые три хода, default (из 40 прокатов):**

  | что | база | B | A | C |
  |---|---|---|---|---|
  | `cat README.md` в первом ходу | 39 | 40 | 40 | 29 |
  | запуск `python3 tests/rerun.py` или `runs.py` | 5 | 3 | 1 | 4 |
  | файл `src/` прочитан целиком | 34 | 36 | 37 | 29 |
  | правка в первых трёх ходах | 1 | 0 | 0 | 3 |

- **Ожидание и что вышло.**
  1. Общая цель первой строкой: B не меньше 60 — да (75); A и C не больше 10 — да (0). Изменение увидено.
  2. Вход 09, содержание наблюдения: A и C не меньше 17 — да (20, 20). B «как база» — **нет: 19.** Отступление к
     общей цели лечит не новая цель, а строка «this observation is where to start» и блок.
  3. Ожидание «прогон пройдёт» не больше 8 — **не сбылось, вышло наоборот:** B ≈ 45, A и C ≈ 22 при базе 19.
     Слова «Replayed on your src/ (the model's replies are taken from the log)» читаются как «повтор покажет, что
     модель больше так не делает»: «the replay shows the model no longer emitting an answer argument» (B 05 #0),
     «results change from "wrong result" to "success"» (B 05 #11). На входе 05 так отвечают 19, 16 и 14 из 20.
  4. Путаница ролей не больше 2 из 40 — да: 0 из 120 при 5 из 40 в базе.
  5. thinking без вопроса: сдвига нет, как и ждал.
  6. Первые ходы: у A и B сдвига нет, как и ждал. **У C сдвиг есть, и он вредный:** на входах App README в первом
     ходу читают 4 и 5 из 10 (база 9 и 10), правок в первых трёх ходах 3 (на 09 две сессии правят первым же
     вызовом, ничего не прочитав; одна на втором ходу сдаёт работу).
- **Чего я не ждал.** В A и C слова «the harness handles what the observation describes» читаются буквально —
  «добавить в харнесс обработчик симптома». На входе 09 (починка — в промпте) так отвечают не меньше 8 из 20 в A
  и 6 из 20 в C: «the harness detects/rejects that copied example text» (A #1), «the harness code catches the
  NameError» (C #10), «fail cleanly on the NameError» (A #10). В базе и в B такого толкования нет.
- **Решение по вариантам** (порог тикета: вариант, не изменивший на default ни пересказ, ни первые вызовы, снят;
  принимается сдвиг масштаба G2).
  - **C снят:** бюджет bash последней строкой первого сообщения даёт спешку.
  - **B не принят:** цель прежняя, а ложное ожидание от повтора выросло вдвое.
  - **A не принят как есть:** два изъяна формулировки — слова о повторе и слово «handles».
  - **Что из вариантов годно** (малые числа, но во всех трёх плечах одинаково): две строки ролей прогонов
    («Where it shows» / «What should stay») — путаница 5 из 40 → 0 из 120; строка, что наблюдение одно и с него
    начинать, — на входе без названной починки содержание наблюдения в пересказе 12 → 19–20 из 20.
  - **Что вредно:** описывать механику повтора в постановке; «handles»; бюджет в конце.
- **Что это значит для тикета.** Признак готовности 1 («пересказ на первом ходу совпадает с замыслом») на базе в
  целом уже выполнен ([ST6](ST6-first-turn-base.md)); переписывание постановки первый ход не улучшает и легко
  портит. «На чём видно» надо отвечать не словами в постановке, а строкой в ответе проверки (урок G2). Лимит шага —
  три варианта — исчерпан; исправленный A (без слов о повторе, «the change this observation calls for» вместо
  «handles», бюджет на прежнем месте) не замерен — кандидат в сборку шага 10 или отдельная проба по слову автора.
- **Уверенность.** Средняя для счёта по плечам (20 на клетку, одни seed); низкая для «≈45 / ≈22»: граница разметки
  моя, читал по первым 270 знакам пункта 2. Вывод про C — по 40 прокатам, эффект виден только на двух входах App.
- **Не проверено.** Пересказ после чтения README (ложное ожидание от повтора может уйти). Входы 00–04, 07, 10–14.
  Рассуждения thinking вариантов глазами. Эффект вариантов на первую правку и на конец сессии — здесь не мерился.
