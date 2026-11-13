# EV6 — оценщик 27B NT: ответ по строке на каждый задетый прогон; цель двойным условием

[Указатель проб](../INDEX.md) · хронология: [13.11](../days/1113.md) · прежняя проба: [EV5](EV5-nt-run-blocks.md)

- **Повод.** Автор ушёл до ~12:00: «сам принимай решения что именно тестить, и до моего возвращения тести
  оценщика». Идеи 1 и 2 сабагента на Opus (13.11): рассуждение T перебирает задетые прогоны по очереди, ответ NT
  без рассуждения называет одно место. Поэтому перебор нужно перенести в форму ответа, а цель записать двойным
  условием, из которого следует решающее место.
- **Гипотеза.** EV6a: строка на каждый задетый прогон до вердикта заставляет NT оценить каждый шаг как «часть
  проблемы / нормальный шаг». Тогда вредный шаг вне run 1 не теряется, и цикл, принятый за законный шаг, виден в
  строке. EV6b: цель «каждый шаг, где харнесс поступает иначе, — часть проблемы» связывает эти строки с вердиктом.
- **Что поменялось** (`probes/1112/ev_input.py`, `PROMPTS`; `ev_judge.py --prompt`). Вход — блоки EV5b
  (`--blocks`, кэш `inputs_blocks/`), модель и профиль прежние (`plain27`, T=0, max_tokens 8192).
  - Оба варианта: абзац «You get» описывает вход блоками: «…the steps of the log just before that place and just
    after it (after it, the log shows what the model did with the original harness)»; «what the model would have
    done after that with the edited harness is not known». Это транспорт: в v1 описаны только шаги до места.
  - `runs` (EV6a): цель как в v1. Ответ: сначала по строке «Run N, model call K: what the step in the log was, and
    whether it is part of the problem the observation describes or a step that was fine.» на каждый задетый прогон,
    затем Where и Verdict. Строки «What happens there» нет.
  - `runs_and` (EV6b): то же плюс цель: «It is right when, in the recorded runs, it changes what the harness does at
    the problem the observation describes, and every step where the edited harness acts differently from the log is
    part of that problem. A step that was fine in the log and is now handled differently makes the edit wrong.»
- **Набор.** Те же 21 правка (`runs/ev_1112/t1_mechok_items.json`, слепая разметка, плохих 11, верных 10).
  Сравнение — с EV5b (тот же вход, промпт v1).
- **Риск подгонки.** На этих 21 правке я перебираю подачу уже третий раз. Лучший вариант проверю на отложенном входе
  и на 27B T («опора, не клетка»: правка не должна ухудшать сильную модель).
- **Ожидание (13.11, 03:37 по `date`, до запуска; EV5b ещё идёт, поэтому сравниваю с EV5: 9 из 11 и 4 из 10).**
  - EV6a: плохих 9–11. Не пойманы в EV5 только 75e00c и f0bed9, вред в run 18, и строка на run 18 может их
    поймать. Ложных «Failed» 2–4: строка на run 9 может как исправить ошибку, так и закрепить её.
  - EV6b: плохих не меньше, чем в EV6a; ложных «Failed» не меньше, чем в EV6a, — цель толкает к «Failed», если
    NT принял цикл за нормальный шаг.
  - Ответ длиннее на 100–300 токенов: время на правку + 10–25 с к EV5.
- **Запуск.** `runs/ev_1112/run_ev6.sh`: ждёт конца EV5b, затем `ev_judge.py … --stand plain27 --blocks --prompt runs
  --out t1_plain27_blocks_runs.jsonl` и `--prompt runs_and --out t1_plain27_blocks_runsand.jsonl`.
