# ST5 — опись постановки по строкам (тикет 10.11, шаг 5)

[Указатель проб](../INDEX.md) · хронология: [10.11](../days/1110.md) · тикет: [TICKET-1110-writer](../../TICKET-1110-writer.md)

Разбор без модели, 10.11, 19:19 по `date`. База — `docs/base/4420356/`.

- **Механическая часть** — `docs/base/4420356/inventory.tsv`, 86 фраз: системный промпт по предложениям, описания
  инструментов, README обоих бенчей. У каждой — самый ранний коммит, где строка есть в нынешней записи
  (`git log -S` по первым 60 знакам; для строк, собранных из шаблона, дата поздняя — это видно по хэшу снимка),
  и число сессий из 120 (PL, PK, G3–G9), где модель повторяет пять слов фразы подряд. Сборка —
  `probes/1110/inventory/origin.py`; сообщения харнесса — `probes/1110/inventory/messages.txt`.
- **Цитирование — нижняя оценка:** на стенде default текста у модели почти нет, а совпадение по словам ловит и
  общие обороты («goes exactly as in the log» стоит в трёх разных строках).

## Фразы, от которых зависит, что писатель считает задачей

«Ф» — факт о среде, «Т» — толкование или указание, как работать. «Ничем» — замера, который показал бы, что фраза
делает своё дело, в журнале нет.

| # | где | фраза | зачем | откуда | чем подтверждено | Ф/Т | с чем спорит | цитирует |
|---|---|---|---|---|---|---|---|---|
| 1 | system | «Your goal: change src/ so that the agent fails fewer tasks.» | цель | 10bcde9, 29.10 | [G1](G1-goal-line.md): замена на «сделать то, что описывает наблюдение» — 1 → 3 из 10, не установлено | Т | с меркой «точно реализовать вход»; с 12 и 13, где целью названо другое | 16 |
| 2 | system | «Each observation that points to a weakness… is a candidate for a change.» | выбор из нескольких наблюдений | 29.10, когда на вход шёл отчёт из 6–11 наблюдений | ничем | Т | с первым сообщением: наблюдение одно | 2 |
| 3 | system | «An observation may also be inaccurate, or point to something the harness cannot change; what it says about src/ you can check by reading src/.» | право не верить входу | 29.10 | ничем: неверных входов в наборе нет ([ST3](ST3-input-map.md)) | Т | с 4 | 0 |
| 4 | system | «The runs are in logs/: trust your colleague initially; if you are confused, you may check the logs.» | не перепроверять наблюдение по логам | db6ca35, 4.11, слова автора | [NT](../1106/NT-no-trust.md): без фразы 6/3/8/13 против 4/2/8/16 — шум | Т | с 3; с 12: чтобы не задеть прогон keep, его надо читать | 0 |
| 5 | system | «The same harness runs on every task the agent gets, so aim for changes that help on tasks in general.» | общность правки | 29.10 | ничем | Т | с 11: тикет требует изменения в одном названном прогоне | 6 |
| 6 | system | «Read the part of src/ a change touches before you edit it, and keep intact what the rest of the harness relies on.» | порядок работы | 29.10 | ничем | Т | — | 2 |
| 7 | system | «Checks run by themselves: after each edit that is applied, pyflakes, smoke и rerun… this uses no bash calls.» | проверка бесплатна | baa52c4, 6.11 (AC) | AC: механика включилась; по вердиктам — шум | Ф | с 9 складывается в экономику «читай всё, правь в конце» | 1 |
| 8 | system | «If the runs an observation is about show no changes, your change may have missed.» | «no changes» читали как успех | AC, 4.11; нынешняя запись a13b543 | ничем отдельно; после строки Failed тикета дублирует её | Т | — | 0 |
| 9 | system | «bash can be called 25 times; after that 3 turns remain without bash: edits are still applied and checked after each one, and then the session ends.» | бюджет фактом | 59ea5e9, 6.11 (PL) | [PL](../1106/PL-plain-clean.md): отказов bash после конца 31 против 21 — не меньше; вердикты — шум | Ф | даёт экономику: правка после конца ничего не стоит | 7 |
| 10 | первое сообщение | «Observation from a study of the agent's failed runs (references to logs/ point to the runs in logs/):» | заголовок входа | входы `typed_1110`, вне git | ничем | Ф | — | — |
| 11 | первое сообщение | «Change expected: control — what the harness code does in run N should change, not only the texts the model reads.» | ожидание ревьювера | 1c3a6e5, 6.11 (TKS) | [TKS](../1106/TK-TKS-ticket.md): по вердиктам шум; модель слова повторяет | Ф о проверке | с 1 и 5: узкая цель против общей | до 38 |
| 12 | первое сообщение | «Run K passed without this change: the goal is that it still goes exactly as in the log once the change is in.» | вторая половина тикета | 02f2b77, 6.11 (TKK); слова менялись 10.11 (c918594) без серии | TKK 8/3/5/14 на чистой базе не повторился: [PK](../1109/PK-keep-plain.md) 5/2/7/16 | Т («the goal») | второе «goal» в постановке; «exactly as in the log» строже нужного: правка класса прогонов законно меняет класс | до 48 |
| 13 | первое сообщение | «The check after each edit tells you whether each of the two holds.» | где смотреть | 02f2b77, 6.11 | ничем | Ф | занимает место «готово»: Ok читается как конец работы (REPORT-1106; finish после Ok — 61 %) | до 28 |
| 14 | первое сообщение | «Change src/ so that the agent fails fewer tasks.» | задание | 29.10 | ничем | Т | повтор 1 последней строкой, уже после тикета: последнее, что читает модель, — общая цель | 19 |
| 15 | заметка | «You have used all 25 bash calls. bash is no longer available. Edits are still applied and checked after each one; 3 turns remain, then the session ends.» | конец bash фактом | 768f357, 6.11; слова 10.11 | PL: не уменьшила отказы | Ф | — | 17 |
| 16 | отказ | «Error: bash is no longer available; this command was not run.» | отказ | ff33255, 30.10 | после конца bash модель всё равно зовёт bash: в F2/F2b 11 продолжений из 20 | Ф | — | 11 |
| 17 | ответ на повтор | «This command was already run at tool call N, and no file has changed since… Running it again tells you nothing new: change the command, or go on from this output.» | повтор команды | 768f357, 6.11, слова автора | офлайн-проба 6–7.11; на сессиях — ничем | Ф + совет | — | 1 |
| 18 | проверка | «Failed: this edit has no effect in run N, the run the observation is about» + факт о мёртвом условии со значениями | правка мимо | 5059a5d, 10.11 | [G2](G2-failed-wording.md): прежнюю строку читали как успех 5 из 10, новую — 0. Единственная строка постановки с замером такого масштаба; один вход, один набор префиксов | Ф | — | 3 |
| 19 | проверка | «Ok: in run N the harness now acts differently: …» | правка действует | b8f8e4e, 6.11 | читается как «готово» (REPORT-1106) | Ф | с меркой: «действует иначе» не значит «делает то, что описано» | 9 |
| 20 | проверка | «Ok: run K, which passed, still goes exactly as in the log.» / «Failed: this edit changes run K, which passed and should still go exactly as in the log; …» | keep | c918594, 10.11, без серии | ничем | Ф / «should» — Т | как 12 | до 48 |
| 21 | проверка | «python3 tests/smoke.py runs without errors. With the stub task and model the harness says the same as before your edits.» | что добавила правка на заглушке | 7a158ce, 10.11, без серии | ничем | Ф | может читаться и как «всё хорошо», и как «правка не действует» — не размечено | 7 |
| 22 | README | пример вывода rerun «from the harness of another agent»: хук `on_observation`, `harness.make_ctx`, словарь `ctx` | показать формат вывода | 39ebcf4, bda5669, 4.11 | ничем | Ф о формате | с видами `typed_1110`: хуки там типизированы, `on_observation` и `ctx` нет. В PL s3 и PK s3 (виды ещё до типов) на входе 09 писатель написал хук `on_observation`, которого харнесс не вызывает | 19 (строки примера) |
| 23 | README | `python3 tests/rerun.py N --at K` | значения в точке | bda5669; в README всегда с 10.11 | как строка промпта (W14) не принят; в README — без серии | Ф | — | 1 |
| 24 | README | `tests/runs.py steps N`, `show N a-b` | читать прогон коротко | f154d23, 10.11 | ничем: серия TY отложена | Ф | — | 1 |

## Что в постановке сказано о том, для чего bash

- Что это: «a read-only shell in the working directory», список программ, «Nothing can be written with it» (про
  запрет записи — четыре раза: в системном промпте у bash дважды и у python3, и в описании инструмента).
- Как им читать: «read big files in parts (sed -n '40,90p' FILE, head, tail) and search with grep -n».
- Два применения: «if you are confused, you may check the logs» и «To look at one run in detail, run python3
  tests/rerun.py N yourself».
- Сколько стоит: 25 вызовов; проверки бесплатны.
- **Не сказано:** для чего bash в этой задаче. Что им узнают форму данных, которые получает хук, смотрят, чем удачный
  прогон отличается от проваленного, проверяют своё условие на прогоне до правки — этого нет ни в одной строке.
  Сказано, чего он стоит, и что чтение логов — на случай «if you are confused».

## Итог описи

- **Цель названа трижды и по-разному:** «fails fewer tasks» (1, 14), «help on tasks in general» (5) и «the goal is
  that it still goes exactly as in the log» (12). Что значит «готово», не сказано нигде; это место занимает 13.
- **Толкования без замера** (кандидаты шага 6): 2, 3, 5, 6, 8, 14.
- **Подтверждено «ничем»:** 2, 3, 5, 6, 10, 13, 14, 20, 21, 22, 24; у 4, 9, 12, 15 замер был и показал шум.
- **Подтверждена замером:** только 18.
- **Вошло в базу 10.11 без серии:** 12 и 20 (слова keep), 21, 23, 24, типы хуков в видах.
- **Спор, которого раньше не называли:** README показывает хук `on_observation` и словарь `ctx` из «другого
  харнесса», а виды типизированы (22).

## Сверка с прошлой сверкой (6.11, 17:05, [день 6.11](../days/1106.md))

| найдено тогда | сейчас |
|---|---|
| «when both hold, the change does what the observation asks» | исправлено 6.11 (02f2b77) |
| конец bash настроен на мир без авто-проверки: «Make the edits you have settled on… then call finish» | исправлено: заметка фактом (15), отказ без «then call finish» (16); хвост по-прежнему 3 хода |
| `--at` известен только из исходника мерки | в README с 10.11 (23), без замера |
| README и комментарии узлов врут | комментарии сняты (голые виды, PL); README собирается заново; README-пример не сходится с типами (22) — новое |
| вход 01 молчит о мёртвой соседней проверке | не исправлено: вопрос 7 автору |
| «Call finish when you are done» трижды | осталось в системном промпте (строка о finish) и в заметке об ответе без вызова |
| цель «fails fewer tasks» дважды | не исправлено (1, 14) |
| «for a few turns» без числа | исправлено: число названо (9, 15) |

**Не проверено.** «Зачем» у фраз 29.10 — по смыслу, записей о них в журнале нет. Цитирование — по словам, не по
чтению. README разобран по трём местам, остальное — только в `inventory.tsv`. Отказы edit и песочницы bash в
таблицу не вошли: их тексты в `probes/1110/inventory/messages.txt`.
