# W0–W17 — rerun и варианты писателя на 10 наблюдениях (W0, W1, W2, W10, W14, W15, W17; формы (а)/(б))

[Указатель проб](../INDEX.md) · хронология: [3.11](../days/1103.md), [4.11](../days/1104.md) · как устроено — [README](../README.md)

<!-- LAB-1103.md:499–508 -->
## 15. rerun — повтор записанных прогонов на новом src, 19:30
- `editor/rerun.py --bench alf|app --src S --logs V/logs [--old V/src] [N ...]`. Модель и задача — из лога; на первом расхождении того, что видит модель или что уходит в задачу, прогон стоп и печатается разница. Промпт отличается → стоп на вызове 1 (решение автора: иначе врём про дальнейший ход). Хуки логируются обёрткой вне src (имя, что вернул, исключение); с --old — какие хуки стали отвечать иначе. Без N — по строке на группу прогонов с одинаковым расхождением; с N — подробно, со строкой лога.
- Проверка инструмента на старом src: 7 видов (ALF r3, chk, n4; App r5, r7, n2, n0) — без расхождений, кроме r5 run 19: в повторе срабатывает защита стенда (3 одинаковых ответа), а в настоящем прогоне не сработала (факт B8 ключа: защита тогда не действовала).
- Восстановление App: в логе ответ модели уже после обрезки харнессом (+"\n\n"); подаю без хвоста. Текст после блока кода в логе потерян.
- Ночные поломки: ALF n4_2 — все 40 прогонов (30 удачных) обрываются на вызове 3 «You are stuck». App n2_0 — промпт изменён (стоп на вызове 1); только код — сообщение после каждого шага во всех 30. **App n0_2 только код — харнесс падает во всех 30 прогонах на шагах 1–6: `_track_action` AttributeError 'Assign'.target; хук on_before_action падает на каждом шаге, не только на complete_task.** Мой вход (б) §12 про n0_2 был неполон.
- 20:40. rerun: смешанные расхождения проверены на 4 вариантах (блок недопустимого действия ALF — 19 из 29 прогонов на разных вызовах; хук отвечает, но харнесс игнорирует — «same as the log; hook … (was None)»; код переписан перед отправкой в задачу — «the code run in the task differs» с - и +; детектор цикла — 3 из 40, плюс «сообщение после последнего шага»). Группировка — с точностью до строк в кавычках и чисел. Повтор теперь в одном процессе (<1 с на вид).
- Писателю — флаг `--rerun`: в копии `logs/` вида, `tests/rerun.py`, `tests/orig_src/`; в README описание и пример вывода на выдуманном агенте (подсказка «осталось 5 шагов»); в промпте «runs are in logs/» и «run python3 tests/smoke.py and python3 tests/rerun.py». Проверено в песочнице писателя: без правки — «same as the log»; с ночным harness ALF — «all 40 runs … model call 3».
- 4.11. Пример в README rerun заменён по слову автора: вместо «осталось 5 шагов» — хук, который пишет «foobar», когда в наблюдении есть и «foo», и «bar» (не наводит на приём). База для тестов на ручных входах — писатель дерева, плечо obs (решение автора). Страница для просмотра автором: промпт целиком (база и `--rerun` построчно), пример входа (наблюдение 00, форма (в)), README, все 10 наблюдений в форме (в) с (в+k) — собрана из `--dry`, сверена с ним байт в байт. Шапка входа с `--rerun`: «references to logs/ point to the runs in logs/».
- 4.11. Строка `--rerun` в промпте по слову автора: «The runs are in logs/: trust your colleague initially; if you are confused, you may check the logs.» Страница вариантов писателя для просмотра автором: W0 база (obs дерева), W1 +rerun, W2 +rerun + цель за 5 bash до конца (не реализовано, текст), W3 +rerun +checked — промпт целиком из `--dry`, вход с примером (наблюдение 00, (в)), сообщения харнесса писателя по ходу. Отмечено: строка README логов «Read the failed runs; the passed runs are there for comparison and grep» спорит с «trust your colleague initially».

<!-- LAB-1103.md:509–545 -->
## 16. Варианты писателя на 10 наблюдениях, 4.11
- **Решения автора.** Пример README — хук «foobar». Строка `--rerun`: «The runs are in logs/: trust your colleague initially; if you are confused, you may check the logs.»; строка README логов «Read the failed runs…» у писателя убрана (спорит с доверием коллеге). W2 — «сделай, пробуй». Число bash (15/30/50) — потом, на лучшем W. W4 — более подробный rerun; W5+ — из документа автора «9B-писатель правок харнесса: rerun, промпты, варианты».
- **W2 = `--goal-k K`** (cfg.GOAL_K, phase.after_turn): когда bash осталось ≤K, одно сообщение «N bash calls are left. Goal now: check your latest edits with python3 tests/smoke.py and python3 tests/rerun.py.» Проверено симуляцией after_turn без модели: при K=5 сообщение после хода, где bash стал ≥20, затем финальные ходы как раньше.
- **Дефект rerun до запуска (мой).** На нетронутом src r5app run 19 (наблюдение 02!) показывал расхождение: защита стенда в повторе срабатывала, а в настоящем прогоне её не было (B8). Писатель увидел бы «баг уже меняется» на исходном коде. Исправлено: защита стенда — только если запись ею кончилась; если запись оборвал стенд (`stopped`: контекст) ровно на запросе, который харнесс делает дальше, — расхождения нет. Все 6 видов наблюдений на старом src — «same as the log to the end», смешанные варианты v1–v4 дают прежний вывод.
- **Задания** `wv_<наблюдение>_<W>` (qj.sh `wv`, выход `runs/wvar_1104/`): 10 наблюдений, форма (в), seed 1; W1 (`--rerun`) и W2 (`--rerun --goal-k 5`) вперемешку, затем W0 (база, obs дерева). Входы — `runs/manual_1103/v2/in/NN_v_{base,rr}.txt` (шапка: логи «not in this copy» / «in logs/»). 30 сессий.
- **Мерка.** Ручное чтение diff и логов по каждой сессии: правка живая/верная по `rerun` на виде наблюдения (задевает ли прогон тикета, срабатывает ли везде, падает ли) + чтение. Процесс: запускал ли писатель rerun, был ли rerun после последней правки (W2 против W1).
- **Ожидание.** W2 против W1: больше сессий с rerun после последней правки. W1 против W0: меньше «срабатывает везде» и «не задевает свой баг».
- **W10 = `--goal-text FILE`** (cfg.GOAL_TEXT, turn.run_calls): якорь цели (форма GOAL-a документа автора: Observation / Expected / Actual / Your task now) дописывается к последнему выводу инструмента каждого хода, кроме хода с finish. Проверено заглушкой do_call. Строки на 10 наблюдений — `runs/manual_1103/v2/goal/NN.txt`, писал я; сверка свежим агентом Opus по наблюдениям, логам и src: 7 верны, 3 исправлены — 00 («молчит до лимита» ложно: с шага 46 отсчёт шагов), 04 (Expected описывал механизм, не поведение), 09 (5 раз, не 4; «word for word» — только последний шаг примера). Задания `wv_NN_W10` = W1 + якорь, после W0.
- **Решения автора, 4.11 ~01:15:** писатель с thinking — не сейчас; T=0.3 — «на здоровье»; W14, W15 — «пробуй».
- **W14 = `--rerun --rerun-at`:** `python3 tests/rerun.py N --at K` — повтор прогона N на текущем src до вызова модели K; печатает две строки лога перед ним и все вызовы функций src/harness.py и src/hooks.py на этом шаге с настоящими значениями аргументов и результатов (строки до 100 символов, у длинных списков последние 3, словари до 2 уровней, повтор значения — «<same as above>»). Бьёт в «выдуманные данные» (§13: писатель проверял функцию на сочинённых значениях). README — пример на агенте «foobar»; в промпте к строке проверки: «To see the values your code gets at a step of a real run, run python3 tests/rerun.py N --at K». Проверено в песочнице писателя: ALF n4 run 6 --at 20 — 3956 символов (видны history.last_actions перед stalled), App r5 run 1 --at 15 — 5881; ошибки аргументов дают usage.
- **W15 = `--rerun --finish-review`:** первый finish при хотя бы одной применённой правке не завершает: показывает diff всех правок от начала (до 5000 символов) и вывод python3 tests/rerun.py (до 2500), «If this is the change you meant, call finish again; otherwise change it with edit.» Вместе с прежними воротами (pyflakes, падение smoke). В финальных ходах — +1 ход на ответ. Проверено на копии с правкой-детектором цикла.
- **W17 = `--rerun --temp 0.3`** (флаг `--temp` поверх профиля стенда).
- Очередь после W0: W10, W14, W15, W17 — по 10 сессий; всего 70, это ~10–12 ч на 4 слотах.
- **Первые 6 сессий (W1/W2 на 00–02, 03_W1), 01:19–01:46 — ни одной живой правки** (rerun итогового src: прогон тикета «same as the log»). 00_W1 и 00_W2 при одном seed идут одинаково до сообщения-цели (пары по построению). 00: порог «<3 разных наблюдений из 6» при 3 разных в цикле run 6 (писатель сам посчитал по логу: 5 разных) — мёртво на 6, на 4 и 13 обрывает эпизод; 5 bash ушли на запись файла через bash. 01_W1: функция `in_a_cycle` не вызывается. 01_W2: детектор не срабатывает. **02_W2: rerun после правки — «all 9 runs: same as the log to the end», писатель: «Both tests pass», finish** — вывод rerun без расхождений читается как успех. Цель W2 пришла в 01_W2 и 02_W2; rerun на последней правке после неё — ни разу.
- **Решение автора, 01:50:** писать «no changes» и объяснить в промпте: если no changes — возможно, правка мимо. Сделано: группа без расхождений — «no changes (same as the log to the end)»; README: «`no changes` means that in those runs the current `src/` gives the model and the task exactly what the log has»; строка проверки в промпте `--rerun`: «If python3 tests/rerun.py shows no changes in the runs an observation is about, your change may have missed.» Очередь на паузе; 4 идущие сессии (02_W1, 03_W2, 04_W1, 04_W2) остановлены; все 10 начатых W1/W2 — в `runs/wvar_1104_v0/` (старая формулировка), запускаются заново с новой. Все варианты ночи — с новой формулировкой.
- **Чтение 16 сессий W1/W2 (новая формулировка), до 03:15** — `runs/wvar_1104/READ.md`: живых верных 2 (02_W1 — повтор исполняется и тратит шаг; 06_W1 — блок действия не из списка), правдоподобный промпт 1 (05_W1), живых широких 3 (01 ×2, 04_W2: «код из недавних» — срабатывает и в удачных 8, 20), мёртвых/мимо/ломают/без правок 10 (08_W1 — NameError во всех прогонах, правки вслепую в финальных ходах; 08_W2 — сравнение наблюдения с историей в нижнем регистре). rerun после последней правки — 6 из 16.
- **Решение автора, 03:20:** rerun после «сдачи» — во все варианты, не опцией, вынужденно, с вопросом «это ок?» и возможностью сдать ничего; всплывает ответным сообщением на finish. Сделано (`--finish-review`, gate.finish): при каждом finish, если src изменился после прошлого обзора, — «Not handed in yet»: diff всех правок, вывод rerun, «Is this the change the observation needs? If it is, call finish again to hand it in. If not, change it with edit; or, if you think you could not make it, call finish with submit=false to hand in nothing.» `finish(submit=false)` — правки отбрасываются (diff — в лог сессии, запись `dropped`), src как в начале. Схема finish и строка Tools с `submit` — только с флагом. Проверено на копии: обзор → finish → конец; правка после обзора → обзор снова; submit=false → diff пуст.
- **Пары.** W0/W1/W2 считаются без обзора (почти досчитаны). Обзор добавлен в ещё не начатые W10, W14, W17; W15 (`--rerun --finish-review`) = «W1 + обзор» — их база и мера самого обзора против W1. Флаг остаётся только ради пар этой ночи; дальше — во всех вариантах с rerun.
- **Идея автора, 03:30 (на потом):** несданные (`finish(submit=false)`) — доработать свежим агентом: новая сессия писателя на том же наблюдении, вход — наблюдение + отброшенный diff (запись `dropped` в логе) и/или вывод rerun на нём. Сначала посмотреть, как часто и на чём писатели сдают ничего (W15/W10/W14/W17 этой ночи).
- **Итог W1/W2, 03:40** (20 сессий, `runs/wvar_1104/READ.md`): W1 — живых верных 2 (02, 06), правдоподобный промпт 2 (05, 09), широкая 1, брак 5; W2 — живых верных 1 (07), широких 2, брак 7 (вкл. 2 без правок, 09_W2 — подгонка «venmo» в коде). rerun после последней правки: W1 3 из 10, W2 4 из 8 с правками. Цель за 5 bash до конца (W2) заметно не помогла: по одному seed W1 и W2 идут одинаково до цели, и после неё последняя правка проверена в 4 из 8; качество не выше W1. На 10 наблюдениях × 1 seed это различие не отличимо от разброса.
- **W0 (база), 05:00** — `runs/wvar_1104/READ.md`: живых верных 2 (02, 03), промпт 1 (09), широкая 1 (01), брак 6. **W1 (rerun) против W0 по счёту не лучше:** 2/2/1/5 против 2/1/1/6; по наблюдениям вперемешку (03 верна у W0 и против наблюдения у W1; 06 наоборот). Брак тех же видов в обеих: не та форма данных (06_W0 `ctx["action"]`, 08_W2), обрыв эпизода (00_W0, 07_W0, 00_W1/W2), широкое «код из недавних» (01 во всех трёх). Вывод только про эту выборку (10 наблюдений × 1 seed): rerun как инструмент писатель запускает, но выход «есть расхождения в удачных» и «no changes на тикете» не меняет его решения.
- **W10, 05:20** (`runs/wvar_1104/READ.md`): верных 2 (02, 07), широких 2, брак 6 — не лучше W0/W1. Якорь цели не помешал повторить те же браки (05 — пример без answer уже в 3 вариантах). **Обзор при сдаче:** дошли 5 из 10, `submit=false` — 0; 06_W10 увидел в обзоре pyflakes «redefinition of unused 'on_before_action'» и no changes на всех 29 и ответил «The change is exactly what the observation needs». **Дыра:** 5 из 10 кончились по лимиту bash (forced) — обзор не показывается, он только на finish. Закрыть: обзор в сообщении о конце bash (финальные ходы). Не меняю ночью: W14 уже идёт, W15 — база для W10/W14/W17; на следующий заход.
- **W14, 06:15**: `--at` запускали 8 из 10 — включился; верных 2 (02, 06), широкая 1, брак 7. Не лучше. Мёртвые условия остались (00, 04, 08 — 08: «все наблюдения истории равны первому»): настоящие значения писатель видел, но условие на них не проверял. Обзор: 5 из 10, ничего не сдал никто; 07_W14 сдал правку, обрывающую эпизод на первом текстовом ответе.
- **W15 (W1 + обзор), 07:20**: верных 2, промпт 1, широких 2, брак 5 — как W1 (2/2/1/5). Обзор показан 5 раз, `submit=false` — 0; 09_W15 видел в обзоре «no changes» на всех 30 и хук, чей ответ харнесс не берёт, и сдал. 06_W15: код мёртвый (`ctx["raw"]`), но писатель не мог это увидеть — правка промпта закрыла rerun (W9).
- **W17 (T=0.3), 08:30**: 2/1/1/6 — как остальные.
- **Итог ночи 4.11** (70 сессий, 7 вариантов × 10 наблюдений × seed 1; матрица — `runs/wvar_1104/READ.md`):
  - **Варианты между собой не различаются**: живых верных 1–2 из 10 у каждого, брак 5–7. Разброс — по наблюдениям, не по вариантам: 02 верна в 6 из 7, 01 широкая в 7 из 7 (всегда «код из недавних шагов»), 00 и 08 (циклы ALF) — брак в 7 из 7, 05 ломает пример (answer убран у вопроса) в 5 из 7.
  - **Инструменты включаются, решения не меняются**: rerun запускают, `--at` — 8 из 10, обзор при сдаче показан 19 раз — «сдать ничего» 0 раз; «no changes» на тикете и расхождения в удачных писатель видит и объясняет (00_W1, 06_W10, 09_W15).
  - **Повторяющиеся браки**: условие на данных не той формы (ключ ctx, которого нет: `action`, `raw`; нижний регистр истории), ответ хука, которого харнесс не берёт (`stop`, сообщение on_init), обрыв эпизода вместо сообщения, NameError/TypeError в сданном коде (обзор не показан: конец по лимиту bash).
  - **Не пробовали**: другие seed (1 seed — различия в 1 сессию неотличимы от разброса); формы (а)/(б); обзор в конце bash (дыра: 21 из 40 сессий с обзором кончились по лимиту); rerun со старым промптом (W9; в 06_W15 правка промпта закрыла проверку кода); W5 (предсказание), W8 (rerun после каждой правки).
- **Моя ошибка, 4.11.** Формы (а)/(б) ночью не запускал: слово автора «показывай все в форме (в)» было про просмотр, я перенёс его на запуск и не спросил. Очередь пуста с 06:59 — машина стояла до ~10:30, следом ничего не поставил.
- **(а)/(б) × W1, W15, 4.11 ~10:30 (решение автора: «w1 и w15 самые вкусные»).** Входы `in/NN_{a,b}_rr.txt` — урезание `NN_v_rr.txt` (та же шапка; (б) — до «Logs:», (а) — до «Code:»), тела сверены с разделами (а)/(б) в `obs/NN_*.md` — совпадают все 10. Задания `wv_NN_{W1,W15}{a,b}`, 40 сессий, seed 1, выход `runs/wvar_1104/`. Пары: по одному seed каждая сессия парна с ночной (в) того же W до первого расхождения входа. Ожидание: в (а) больше «мимо» и «не та форма данных» (писатель сам ищет место и данные); вопрос — помогают ли логи (в) против (б) и код (б) против (а).
- **(а) прочитана целиком, (б) — 5 из 20, 17:40** (`runs/wvar_1104/READ.md`). (а): W1 2/1/1/6, W15 2/0/0/8 — против (в) W1 2/2/1/5, W15 2/1/2/5. Без кода писатель тратит bash на поиск места (до 21 из 25 на чтение), кончает по лимиту в 13 из 20 и правит вслепую: 4 сданных правки падают (NameError/KeyError/IndexError). Новое верное в (а): 01_W15a — блок шагов повторяет прежний, задевает только проваленные. **00_W15b — первый `submit=false`**: последнюю правку проверить было нечем, сдал ничего; отброшенный diff по rerun мёртв. Моя ошибка: первые сессии не прочитал сразу после окончания, как обещал, — прочитал на вопрос автора.
- **Разбор свежим агентом (Opus), «есть ли логика в оценке автора W1/W15 > W0/W10/W17 > W2/W14», 4.11 вечер.** Вывод агента: логика узкая. (1) W1 и W15 не парные: строка `finish(submit)` в промпте разводит сессии с хода 1; обзор W15 ни разу ничего не изменил (5 раз — сразу повторный finish). (2) W2 против W1 — единственная настоящая пара: в 00, 01, 05, 06, 08, 09 ходы совпадают дословно до сообщения-цели. Цель «check your latest edits» пришла до первой правки в 7 из 10 сессий W2 — посылка ложная, последние bash уходят на rerun нетронутого src; 06_W2 прочёл «no changes» как успех («Run 11 now reproduces the log exactly»), в той же точке 06_W1 запустил `--at` и сделал V. (3) W14 против W15 — логики не видно. (4) Сигнал процесса не по вариантам: правка при живом bash — верных/правдоподобных 12 из 29, вслепую — 6 из 39. (5) Разрыв лучших и худших держится на 05, 09 и двух W2 без правок; по кодовым наблюдениям живых у всех четырёх 3–4. Бонус: W2, W10, W17 не меняют системный промпт своей базы (W2 = W1, W10/W17 = W15 по meta.system) — воздействие только по ходу сессии; строки W2 и W10 совпадают в 9 из 10. Успех на 07 механизму варианта агент не приписывает (07_W2 правил до цели). **Дефект стенда:** `ls -la` в копии печатает время её создания — пары W1/W2 расходятся с хода 1 в 02, 03, 04 и с хода 6 в 07; для парных сравнений время файлов в копии надо фиксировать. Скрипты агента: scratchpad `wv/`.
- **Причины брака по всем не-V сессиям (свежий агент, тот же), 4.11 вечер.** 98 сессий (70 (в), 20 (а), 8 (б)), не-V 79: отнесено к наблюдению 52, к процессу 22 (падение, не тот ключ ctx, ответ хука, который харнесс не берёт, 0 правок по концу bash), к варианту 3 (03_W2, 06_W2, 09_W2 слабо — все три «цель до первой правки»), к случаю 2 (02_W2, 07_W2/W1 — развилка из-за времени в `ls -la`). Последняя правка вслепую (после конца bash): 51 из 74 не-V с правками против 8 из 19 у V. Пары: общий префикс только у W1–W2; W10/W15 расходятся на 2–3 ходе, остальные — на 1-м, то есть постановки сравниваются как независимые выборки. В 4 парах W1–W2, разошедшихся только из-за `ls -la`, исход перевернулся в 3 — масштаб шума от T=0.6 сопоставим с любой разницей вариантов. Набор идей на наблюдение узкий и от варианта не зависит: 01 — «код из недавних шагов» 10 из 11; 05 — «убрать answer у примера» 7 из 9; 06 — блок недопустимого действия 8 из 9 (пропадает из-за реализации); 07 — три идеи, выпадает случайно; 00, 08 — работающей идеи нет в 20 попытках. **Вывод:** варианты действуют в конце сессии (проверка, обзор, цель), а исход решается раньше — выбором идеи, обычно уже вслепую. Температура решает, какая из 1–2 идей выпадет и сломается ли реализация.
- **(б) прочитана целиком, 19:20.** W1 (а)/(б)/(в): V 2/2/2, брак 6/6/5; W15: V 2/2/2, брак 8/7/5. Решённые — те же 02, 06, 07 (плюс 01_W15a). Падений вслепую в (б): 3 (04 ×2, 09_W15b). Форма входа, как и вариант, на набор идей не влияет; разница в браке 1–3 сессии — в пределах разброса. Согласуется с разбором причин: исход решает выбор идеи. Следующий шаг (план с автором): генерация идей и выбор идей отдельно от писателя.

## Код

<!-- LAB-1103.md:546–674 -->
**Код пробы** (приписано 10.11). Из кода убран в a13b543: в develop осталась одна база. Последний коммит с этим кодом — 951bc3b (`git show 951bc3b:ФАЙЛ`); номера строк в листинге — по нему.

`--goal-k K` (W2)

```python
# nrhsi/editor/phase.py:38-44
elif C.GOAL_K and not run.goal_sent and run.st["bash_calls"] >= C.BASH_LIMIT - C.GOAL_K:
    run.goal_sent = True
    checks = "python3 tests/smoke.py and python3 tests/rerun.py" if C.RERUN else "python3 tests/smoke.py"
    from . import work as WK
    checks = WK.tt(checks)
    run.note_user(f"{C.BASH_LIMIT - run.st['bash_calls']} bash calls are left. Goal now: check your latest edits "
                  f"with {checks}.")
```

`--goal-text FILE` (W10)

```python
# nrhsi/editor/cli.py:270
C.GOAL_TEXT = open(a.goal_text).read().strip() if a.goal_text else None

# nrhsi/editor/turn.py:90-93
if C.GOAL_TEXT and not finished and run.messages[-1]["role"] == "tool":   # --goal-text: якорь в конце хода
    run.messages[-1]["content"] += "\n\n" + C.GOAL_TEXT
    run.pending += F.est_tokens(C.GOAL_TEXT)
    rec["results"][-1]["goal"] = True
```

`--rerun-at` (W14): строка промпта; описание `--at` в README с c918594 стоит в базе всегда

```python
# nrhsi/editor/prompt.py:90-91
RERUN_AT_LINE = (" To see the values your code gets at a step of a real run, run python3 tests/rerun.py N --at K "
                 "(see README.md).")

# nrhsi/editor/cli.py:135-137
if a.rerun_at:
    esys = esys.replace(P.RERUN_CHECK_LINE, P.RERUN_CHECK_LINE + P.RERUN_AT_LINE)
    assert P.RERUN_AT_LINE in esys
```

`--finish-review` (W15)

```python
# nrhsi/editor/prompt.py:92
FINISH_LINE = "- finish(): end the session when your changes are done."

# nrhsi/editor/prompt.py:93-96
FINISH_REVIEW_LINE = ("- finish(submit): hand in your changes and end the session. Before they are handed in, you see "
                      "all your changes and what python3 tests/rerun.py prints on them; then call finish again to hand "
                      "them in, change them with edit, or call finish with submit=false to hand in nothing (src/ goes "
                      "back to how it was at the start).")

# nrhsi/editor/schema.py:31-35
FINISH_SUBMIT_SCHEMA = {"type": "function", "function": {
    "name": "finish", "description": "Hand in your changes and end the session; submit=false hands in nothing.",
    "parameters": {"type": "object", "properties": {
        "submit": {"type": "boolean", "description": "false: drop all your changes, src/ goes back to how it was at "
                   "the start, and nothing is handed in. Default true."}}}}}

# nrhsi/editor/cli.py:138-140
if a.finish_review:
    assert a.rerun and P.FINISH_LINE in esys, "--finish-review needs --rerun"
    esys = esys.replace(P.FINISH_LINE, P.FINISH_REVIEW_LINE)

# nrhsi/editor/gate.py:24-57
def finish(run, args=None):
    """finish -> (текст для модели, конец ли). Шаг вариантов — конец сразу. Редактор: ворота pyflakes и smoke —
    один раз; --finish-review — обзор (все правки и rerun на них) при каждом finish после изменения src;
    finish(submit=false) — правки отбрасываются, src как в начале."""
    if run.role != "editor":
        return "Finished.", True
    from . import work as WK
    if C.FINISH_REVIEW and (args or {}).get("submit") in (False, "false", "False"):
        d = WK.diff_src(C.BENCH, run.root)
        run.w({"type": "dropped", "diff": d})
        WK.restore_src(C.BENCH, run.root)
        run.st["submitted"] = False
        return "Finished: nothing handed in; src/ is back to how it was at the start.", True
    h = WK.tree_hash(f"{run.root}/src")
    review = C.FINISH_REVIEW and run.st["edits_applied"] and h != run.st.get("reviewed_hash")
    if run.st.get("lint_at_finish") and not review:
        return "Finished.", True
    gate = "" if run.st.get("lint_at_finish") else LI.lint_changed(run.root)
    smoke = "" if run.st.get("lint_at_finish") else smoke_failure(run)
    if smoke:
        gate += ("\n" if gate else "") + smoke
    run.st["lint_at_finish"] = True
    if not review:
        if not gate:
            return "Finished.", True
        return f"Not finished yet. {gate}\nFix them with edit, or call finish again to end as is.", False
    run.st["reviewed_hash"] = h
    run.st["reviews"] = run.st.get("reviews", 0) + 1
    if run.final_left and run.st["reviews"] == 1:
        run.final_left += 1                  # ход на ответ после первого обзора
    return (f"Not handed in yet. Here are all your changes and what {rerun_name()} prints on them."
            + (f"\n{gate}" if gate else "") + f"\n\n{review_text(run)}\n\nIs this the change the observation "
            "needs? If it is, call finish again to hand it in. If not, change it with edit; or, if you think you "
            "could not make it, call finish with submit=false to hand in nothing."), False

# nrhsi/editor/gate.py:60-69
def review_text(run):
    """--finish-review (4.11): все правки (diff от начала) и вывод python3 tests/rerun.py на них."""
    from . import work as WK
    d = WK.diff_src(C.BENCH, run.root)
    d = d if len(d) <= REVIEW_DIFF else d[:REVIEW_DIFF] + f"\n[... {len(d)} characters in all]"
    out = f"Your changes against the start:\n```diff\n{d.rstrip()}\n```"
    if C.RERUN:
        r = clip(rerun_output(run)[0], REVIEW_RERUN)
        out += f"\n\n{rerun_name()} prints:\n{r.rstrip()}"
    return out

# nrhsi/editor/work.py:263-266
def restore_src(bench, root):
    """finish(submit=false): src/ копии — снова как src/ вида."""
    shutil.rmtree(f"{root}/src")
    shutil.copytree(f"{C.VIEWS[bench]}/src", f"{root}/src", ignore=shutil.ignore_patterns("__pycache__"))
```

`--temp T` (W17)

```python
# nrhsi/editor/cli.py:277-278
if a.temp is not None:
    F.TEMP = a.temp
```


## Связанные записи

- [4.11](../days/1104.md): §17 «Как писатель тратит bash»
- [5.11](../days/1105.md): «Пробы с исходом по построению»: W1 против W15 «парами»
- [6.11](../days/1106.md): «6.11, 17:05 — сверка промпта…»: `--at` (W14) не принят
