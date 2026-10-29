# Редактор харнесса: журнал

## B1 — вход редактора: наблюдения / варианты исправлений (29.10)

Этап: отладка компонента (прогнал → прочитал → починил промпт → повторил), не замер доли успеха.
Вопрос: что лучше давать редактору (9B, `edit(path, old, new)`, чтение `src/`, трасс нет) — (obs) наблюдения
исследователя как есть или (fix) варианты исправлений словами, которые из тех же наблюдений делает промежуточный
шаг (та же 9B, чтение `src/`, без трасс). Локализатор не строил (открытый вопрос дизайна); локализацию делает сам
редактор чтением `src/`.

### B1.0 Что где

| Путь | Что |
|---|---|
| `editor.py` | редактор и шаг вариантов (`--arm obs|fix`), промпты, инструмент `edit`, цикл сессии |
| `fsr_base.py` | снимок `researcher/fsr.py` (sha256 `98001ec5a8b25030`): песочница bash, белый список, обрезка вывода, транспорт. Снимок — чтобы правки fsr.py другим агентом не меняли механику посреди фазы |
| `check.py` | механика правок: компиляция, `import harness, hooks` в venv бенчмарка, тесты бенчмарка на заглушке модели, для AppWorld — слоты `{{ }}` и роли промпта |
| `tests/test_alf.py`, `tests/test_app.py` | копии `tests/test_harness.py` бенчмарков с `SRC`/`ROOT` из окружения (остальное байт в байт) |
| `tests/mock_editor.py` | заглушка модели для `edit`/`propose`/финала (без LLM) |
| `show.py`, `table.py` | сжатый транскрипт сессии; таблица механики |
| `work/<tag>/` | рабочая копия сессии: `README.md` вида без раздела `logs/` + копия `src/` (не жёсткие ссылки); `<tag>_p` — копия шага вариантов |
| `logs/<tag>.jsonl`, `logs/<tag>_p.jsonl` | лог редактора / шага вариантов: meta (полный промпт), ходы, результаты, end (stats, правки/предложения) |
| `out/<tag>.diff`, `.summary.json`, `.check.json` | дифф `src/` против вида, сводка, механическая проверка |
| `launch.sh`, `queue.sh` | запуск одной сессии / очереди пар (obs и fix одного входа одновременно = 2 сессии модели) |

Оригинальные `alfworld/view` и `appworld/view` не менялись: каждая сессия сверяет хэш `view/src` до и после (assert).

### B1.1 Механика (`editor.py`)
- Рабочий каталог: `README.md` вида без раздела `logs/` (механически: строки до `- \`logs/\``) + копия `src/`.
  bash — тот же, что у исследователя (sandbox-exec, только чтение рабочего каталога, белый список программ, обрезка
  8000 символов). Python в песочнице нет.
- `edit(path, old_string, new_string)`, по одной замене за вызов, применяется сразу (запись делает процесс харнесса,
  не bash). Путь — файл в `src/`, кроме `src/bridge.py` (README: «Do not edit»). Пустой `old_string` — запись в
  пустой файл или новый файл в `src/` (иначе пустые `hooks.py`, `no_tool_call.md` не правятся вовсе). Отказы
  возвращаются модели с причиной, файл не меняется: `not_found` («old_string does not occur in src/X; it must be
  copied exactly from the file's current text»), `multiple` (с номерами строк начала вхождений), `same`, `empty_old`
  (пустой old при непустом файле), `path`, `bridge`, `missing`, `args`, `syntax` (правка .py, после которой файл не
  компилируется, не применяется). Успех: «Applied: src/X, the new text is at lines a-b. Lines … now read:» +
  строки с номерами ±2. Диагностик про пробелы/номера строк grep -n/прежние правки нет (пример плохого текста из
  фазы C).
- Шаг вариантов (плечо fix): те же bash и рабочая копия только на чтение, инструмент
  `propose(problem, fix, observations)`. Редактор плеча fix получает только список предложений (problem + fix),
  без наблюдений и номеров наблюдений.
- Лимиты обоих шагов: bash 25 вызовов → финал 3 хода (только edit/propose и finish), бюджет 60 вызовов,
  предохранитель по контексту 54K, T=0.6, seed редактора `1000·seed+11`, шага вариантов `1000·seed+7`, seed=1 у всех.
  Повтор той же команды bash не исполняется, пока файлы не менялись (после применённой правки — снова можно).
- Проверено на заглушке модели (`tests/mock_editor.py`): все виды отказов, запись в пустой hooks.py, новый файл,
  повтор чтения после правки, отказ bash на запись, лимит bash → финал, отказ propose с неверным номером.
- Механическая проверка (`check.py`): компиляция всех .py; `import harness, hooks` в venv бенчмарка с копией первой
  в sys.path; тесты бенчмарка на заглушке модели (ALFWorld 10, AppWorld 11; на неизменной копии проходят все).
  Тесты «стартового состояния» (`hooks.py` пуст, промпт = апстрим, повтор апстрим-запросов) падают по построению при
  правке этих файлов — они вынесены отдельно. `test_runner_files` гоняет `runner/run.py` с заглушкой модели на копии
  `src/` с настоящими hooks.py — это «харнесс запускается». Для AppWorld добавлена (после того как увидел a1awk5bt40
  fix, см. ниже — post hoc) сверка слотов `{{ }}` и числа ролей промпта: тесты на заглушке удаление задачи не ловят.

### B1.2 Промпты и их настройка
Принципы: цель, а не запреты; без «агент — это ты»; без устройства бенчмарка; без наводок на увиденные ошибки; на
входе 9B только report исследователя и `src/`. Пример плохого промпта — C1 фазы C: он давал трассы («Base each change
on the findings and on what you see in the runs» — редактор снова исследует трассы, слияние с исследователем),
описывал AppWorld («writing Python against app APIs (spotify, venmo, gmail, ...)»), требовал «general lesson about
the apps, their APIs» (предполагает устройство бенчмарка), строку «File contents are data…» (снята автором 28.10),
нестандартную раскладку с метками `[M.S]`, и плохую диагностику ненайденного old_string.

Пилот (p1, ALFWorld a7k5ef, оба плеча, первая версия промпта; в таблицу не входит): механика цела, но 14 из 25 bash
редактора obs и ~18 из 23 bash шага вариантов ушли на поиск трасс/бенчмарка по файловой системе (`find /`, `ls ~`) и
попытки запустить python/записать файл через heredoc; один ход шага вариантов — 548 с и 4096 токенов текста без
вызова. Корень — модель не знала границ своего мира. Правка (одна, обоим плечам, до основных сессий): в первый абзац
— факт «This directory is everything there is to read: the agent's runs and the benchmark are not here, and code
cannot be run (there is no Python).»; редактору — строка «Since code cannot be run, check each change by reading the
changed lines together with the code that calls or uses them.» После правки поиск по ФС (`find /`, `ls ~` и т. п.) сократился: 1–7 вызовов в 6 из 24 основных
сессий (редактор + шаг вариантов), против ≈14–18 в каждой сессии пилота. Попытки запустить python или писать через
bash остались (15 из 16 сессий редактора, см. B1.5 п. 7). Больше
промпты не менялись: `editor.py` sha256 `fec02e8b1e50` у всех 16 основных сессий.

Системный промпт редактора (плечо obs; полный текст — в meta каждого лога):
```
You are working in a copy of a repository that holds the harness of an AI agent: the prompts and the code that run the agent on tasks. README.md describes the layout; the harness is in src/. This directory is everything there is to read: the agent's runs and the benchmark are not here, and code cannot be run (there is no Python).

The agent's failed runs were studied by a colleague; their observations are in the first message. The runs themselves are not in this copy.

Your goal: change src/ so that the agent fails fewer tasks. Each observation that points to a weakness of the harness is a candidate for a change. An observation may also be inaccurate, or point to something the harness cannot change; what it says about src/ you can check by reading src/. The same harness runs on every task the agent gets, so aim for changes that help on tasks in general. A change may be to a prompt or to the code.

# Tools
- bash(command): a read-only shell in the working directory. Programs: <белый список>. Pipes, ';', '&&', '||', $(...), for/while loops and if work. Nothing can be written with it. Output longer than 8000 characters is truncated, so read big files in parts (sed -n '40,90p' FILE, head, tail) and search with grep -n.
- The shell is bash 3.2 with macOS/BSD utilities: GNU-only options are missing (use grep -E, not grep -P; no find -printf).
- edit(path, old_string, new_string): replace old_string with new_string in the file at path, a file in src/ (src/bridge.py is not part of the harness, see README.md). old_string must be copied exactly from the file as it is now, spaces and line breaks included, and occur in it exactly once; include enough of the neighbouring lines to make it unique. To add text, put an existing neighbouring line in old_string and repeat it in new_string together with the addition. To write into an empty file or to create a new file in src/, give an empty old_string. Each edit is applied at once and you see the changed lines; an edit that cannot be applied leaves the file as it was and tells you why.
- finish(): end the session when your changes are done.

# How to work
- Read the part of src/ a change touches before you edit it, and keep intact what the rest of the harness relies on: README.md and the comments at the top of the code describe how the parts fit together.
- Since code cannot be run, check each change by reading the changed lines together with the code that calls or uses them.
- bash can be called 25 times; after that only edit and finish remain, for a few turns, and the session ends.
- Call finish when you are done.
```
Плечо fix — те же строки, кроме двух абзацев:
```
A colleague studied the agent's failed runs and proposed fixes for the harness; the proposals are in the first message. The runs themselves are not in this copy.
... Your goal: change src/ so that the agent fails fewer tasks. Make the proposed fixes you judge sound; where several proposals address the same weakness in different ways, choose the way you judge best, or combine them. What a proposal says about src/ you can check by reading src/. The same harness runs ...
```
Первое сообщение obs: «Observations from a study of the agent's failed runs (references to logs/ point to the runs,
which are not in this copy):» + `## Observation i (kind)` / observation / `Evidence:` списком (evidence как написала
модель, `evidence_raw`) + «Change src/ so that the agent fails fewer tasks. Call finish when you are done.»
Первое сообщение fix: «Proposed fixes for the harness, from a study of the agent's failed runs:» + `## Proposal i` /
`Problem:` / `Fix:` + та же последняя строка.

Системный промпт шага вариантов:
```
You are working in a copy of a repository ... (тот же первый абзац) Nothing in it can be changed.

The agent's failed runs were studied by a colleague; their observations are in the first message. The runs themselves are not in this copy.

Your goal: propose fixes to the harness that would make the agent fail fewer tasks. For each observation that points to a weakness of the harness, find where in src/ it comes from and describe how src/ could be changed to remove it. When there are different reasonable ways to fix it (in a prompt or in the code, at one place or another), record each way as a separate proposal. An observation may be inaccurate, or point to something the harness cannot change; what it says about src/ you can check by reading src/. The same harness runs on every task the agent gets, so aim for fixes that help on tasks in general. An engineer will make the changes from your proposals alone, without the observations, so each proposal should be complete on its own.

# Tools
- bash(command): ... (как у редактора)
- propose(problem, fix, observations): record one proposed fix. problem: what goes wrong for the agent and what in src/ causes it. fix: where to change src/ (the file and the part of it) and what the change is, in words precise enough for another engineer to make it. observations: the numbers of the observations it rests on.
- finish(): end the session when your proposals are recorded.

# How to work
- Record each proposal with propose as soon as you have settled on it; several propose calls in one reply are fine.
- bash can be called 25 times; after that only propose and finish remain, for a few turns, and the session ends.
- Call finish when you are done.
```
Первое сообщение: наблюдения (как у obs) + «Propose fixes to the harness for these observations. Call finish when you
are done.»

### B1.3 Входы
Пул — принятые report сессий A1-40 и A7 (free и strict): ALFWorld a1k5t40, a1k5bt40, a1k5et40, a7k5f, a7k5bf,
a7k5ef, a7k5ns, a7k5nf; AppWorld a1awk5t40, a1awk5bt40, a1awk3t40, a7awk5f, a7awk5bf, a7awk5ns, a7awk5nf. Порядок —
механически, до чтения report: `random.Random(1029).sample(sorted(пул), len(пул))` по бенчмарку. Первые три:
ALFWorld a7k5ef, a7k5f, a7k5ns; AppWorld a7awk5f, a1awk5t40, a7awk5ns; потом по времени — четвёртые: a7k5nf и
a1awk5bt40 (в нём 1 report). Итого 4 + 4 входа, по одной сессии редактора на (вход, плечо): 16 сессий редактора +
8 сессий шага вариантов. Новых сессий исследователя нет. Report — как есть (без фильтра верных; доля верных в них по
оценке A7 ≈ 60–70%, на AppWorld много ложных про демо-диалог).

### B1.4 Сессии: механика (по логам и check.py, не загрязнено)
Правки — `edit` применено/попыток (отказы по видам); bash — редактора (+ шага вариантов); отказы — отказы песочницы
(запись, python и т. п.) суммарно; мин — модель, редактор + шаг вариантов (по 2 сессии одновременно, плюс в начале
1 чужая сессия раздела 6). «Запуск» — `test_runner_files` (run.py с заглушкой модели на копии `src/` с её hooks.py).
«Поломка» — моё чтение упавших тестов и диффа (что из упавшего — намеренное изменение формы беседы, а что — поломка).

| бенч | вход (report) | плечо | предл. | edit прим./попыт. (отказы) | bash | отказы | пик prompt | мин | запуск | упавшие тесты (кроме стартового состояния) | поломка харнесса |
|---|---|---|---|---|---|---|---|---|---|---|---|
| ALF | a7k5ef (4) | obs | — | 4/5 (same 1) | 18 | 3 | 20.1K | 9.2 | да | 6: все игры на заглушке без hooks | да: `nb = hooks.nb` — харнесс падает, если в hooks нет `nb` (контракт «хуки необязательны»); состояние общее на процесс |
| ALF | a7k5ef (4) | fix | 7 | 4/4 | 21+15 | 6 | 25.3K | 19.9 | **нет** | runner: экспертный план → repeated action | да: on_post_step подменяет действие на каждом шаге |
| ALF | a7k5f (4) | obs | — | 3/4 (not_found 1) | 25 | 9 | 23.8K | 17.7 | да | 2: сообщения хуков ушли в tool-результат | нет (изменён контракт хуков — намеренно) |
| ALF | a7k5f (4) | fix | 12 | 5/5 | 13+16 | 3 | 19.4K | 18.5 | да | 3: UnboundLocalError `raw`, `run()` возвращает кортеж | да: падение на невалидном вызове; tool-результат без списка AVAILABLE ACTIONS |
| ALF | a7k5ns (8) | obs | — | 0/1 (not_found 1) | 25 | 4 | 10.8K | 4.7 | да | — | нет правок |
| ALF | a7k5ns (8) | fix | 4 | 2/2 | 10+11 | 1 | 14.6K | 11.5 | да | 1: эпизод обрывается на ответе без вызова | да: `continue` → `break` при ответе без tool call |
| ALF | a7k5nf (5) | obs | — | 2/2 | 17 | 5 | 16.2K | 8.0 | да | — | нет |
| ALF | a7k5nf (5) | fix | 6 | 4/5 (not_found 1) | 14+9 | 4 | 15.9K | 10.5 | **нет** | 7: `action.in_admissible` у str — падение на каждом шаге | да |
| App | a7awk5f (4) | obs | — | 5/6 (not_found 1) | 11 | 1 | 14.6K | 5.2 | да | 1: MAX_STEPS 100 ≠ STEP_LIMIT 50 | нет (правка бездейственна: лимит режет run.py) |
| App | a7awk5f (4) | fix | 9 | 9/11 (bridge 1, args 1) | 21+10 | 3 | 22.4K | 12.4 | да | 1: то же | нет (то же) |
| App | a1awk5t40 (5) | obs | — | 4/5 (same 1) | 20 | 2 | 24.2K | 9.3 | да | — | нет |
| App | a1awk5t40 (5) | fix | 3 | 4/4 | 13+20 | 4 | 17.0K | 10.0 | да | 2: новое сообщение каждый шаг (намеренно) | нет |
| App | a7awk5ns (3) | obs | — | 5/6 (not_found 1) | 25 | 7 | 26.9K | 19.1 | да | 2: extract_code; слот app_descriptions пропал, ролей 23→2 | да: незакрытый блок → исполняется текст **до** ```python; демо удалено |
| App | a7awk5ns (3) | fix | 3 | 5/6 (same 1) | 25+13 | 8 | 27.4K | 25.5 | да | 2: extract_code; слот app_descriptions пропал, ролей 23→2 | частично: демо удалено, задача демо осталась без решения |
| App | a1awk5bt40 (1) | obs | — | 2/2 | 25 | 2 | 30.1K | 19.5 | да | — (ролей 23→21) | нет (сообщения склеены) |
| App | a1awk5bt40 (1) | fix | 2 | 2/2 | 14+22 | 3 | 18.5K | 13.9 | да | 1; **слот instruction пропал** | **да: удалены настоящая задача и все Key instructions** — тесты на заглушке этого не ловят |

Итого (8 + 8 сессий):
- obs: edit 25/31 применено (81%; not_found 4, same 2), 92.7 мин модели (сред. 11.6), пик prompt ≤ 30.1K,
  харнесс сломан в 2 сессиях из 8 (a7k5ef — контракт хуков; a7awk5ns — исполнение прозы). Одна сессия без единой
  правки (a7k5ns: 15 из 25 bash — попытки запустить python через `printf … | :`, затем old_string с лишним отступом).
- fix: edit 35/39 (90%; not_found 1, same 1, bridge 1, args 1), 122.2 мин (сред. 15.3: шаг вариантов 5–11 мин +
  редактор 4–16), пик ≤ 27.4K, харнесс сломан в 5 из 8 (a7k5ef, a7k5f, a7k5ns, a7k5nf, a1awk5bt40).
- Синтаксических отказов 0, compile/import цел у всех 16 (у .py правок проверка syntax перед записью).
- Сжатий/предохранителя контекста не было: окно 64K не проблема (пик 10.8–30.1K).
- Сессии кончились finish 14 из 16; 2 — лимит bash (a7k5ns obs, a1awk5bt40 obs). В финале модель дважды звала bash
  вместо edit (a7k5ns obs).

### B1.5 По существу (**моя оценка, одна рука, загрязнено**)
Единица — логическое изменение (одна или несколько правок с одной целью; правки только докстрингов/комментариев не
считаю). Категории: **хорошая** — адресует существующую причину провалов, общая, реализация верна, соседнее не
ломает; **частичная** — то же, но с дефектом (ломает контракт/тест, срабатывает не всегда, не там); **плохая** —
бездейственная (мёртвый код, повтор того, что уже есть), ломает харнесс, противоречит лимиту бенчмарка или следует
ложной посылке наблюдения; **хардкод** — переносит в харнесс конкретику задачи/прогона. Загрязнение: оценивал по
`src/`, диффам и report; какие report ложны, знаю из оценок A1/A7 (сам их не перепроверял трассами в этой фазе).

| бенч | вход | плечо | изменений | хор. | част. | плох. | хардкод | что именно |
|---|---|---|---|---|---|---|---|---|
| ALF | a7k5ef | obs | 4 | 1 | 1 | 2 | 0 | + промпт: «Nothing happened → другое действие, look», не повторять; ± хук «N steps left» каждый шаг; − `nb = hooks.nb`; − хук-переписчик по BLEU (мёртв: bridge уже сопоставил действие) |
| ALF | a7k5ef | fix | 3 | 0 | 0 | 3 | 0 | − won/done в ctx (ветка мертва: при победе эпизод уже кончен); − переписчик (мёртв); − «повтор» сравнивает с первым действием истории и подменяет ходы |
| ALF | a7k5f | obs | 3 | 1 | 1 | 1 | 0 | ± исполнять все tool calls хода (верное наблюдение «только calls[0]»; сообщения хуков перенесены в tool-результат); + промпт «ровно одно действие за ход», опечатка; − хуки (on_init без skills, post_step без kind — мертвы) |
| ALF | a7k5f | fix | 2 | 1 | 0 | 1 | 0 | + промпт: ровно одно действие, дословно из списка, звать инструмент до конца; − переписан цикл: падение, список действий пропал из наблюдения |
| ALF | a7k5ns | obs | 0 | 0 | 0 | 0 | 0 | правок нет |
| ALF | a7k5ns | fix | 2 | 0 | 0 | 2 | 0 | − выход из эпизода на ответе без вызова; − break по won (мёртв) — обе по ложной посылке «выиграл и продолжал» |
| ALF | a7k5nf | obs | 2 | 0 | 1 | 1 | 0 | ± хуки «мало шагов» (post_step работает; pre_hint печатает буквально `{remaining}`; block в post_step мёртв); − лишний break на последнем шаге |
| ALF | a7k5nf | fix | 5 | 1 | 2 | 2 | 0 | + tool_hint «выбирай из AVAILABLE ACTIONS»; ± «мало шагов» в цикле и в хуке (дубль; «choose a final action» — по ложной посылке); − проверка `action.in_admissible` (падение); − лишний break |
| App | a7awk5f | obs | 4 | 1 | 0 | 2 | 1 | + пагинация: до пустой страницы; − MAX_STEPS 100; − новый хук on_repeat_action (читает `nb["history"]`, мёртв); **H** «не ищи song genres, когда задача про playlists» |
| App | a7awk5f | fix | 7 | 2 | 1 | 4 | 0 | + «сначала найди нужный app/API, план словами»; + «spec нужного API»; ± демо: `while True` (переменная токена по-прежнему не определена); − MAX_STEPS 100 (и попытка bridge.py); − хуки мертвы (нет kind / код пуст в pre_hint); − текст о пагинации внутри Output демо; − status="fail" при застревании |
| App | a1awk5t40 | obs | 4 | 0 | 0 | 3 | 1 | − перенос break (без эффекта); − «stay on task» каждый шаг и в промпте — по ложной посылке (демо принято за эпизод); **H** «не изучай song genres, Venmo payments» |
| App | a1awk5t40 | fix | 3 | 1 | 0 | 2 | 0 | + «Steps remaining: N of 50» перед каждым ходом; − хук on_complete после цикла (некому читать); − «если задача уже сделана — complete_task сразу» (ложная посылка) |
| App | a7awk5ns | obs | 2 | 0 | 0 | 2 | 0 | − extract_code (исполняет прозу); − промпт: демо удалено целиком, задача дважды, слот app_descriptions потерян |
| App | a7awk5ns | fix | 3 | 0 | 1 | 2 | 0 | ± «смотри spec, только если не уверен»; − extract_code (предпочитает блок с apis., незакрытый без apis. не исполняет); − демо удалено, задача демо осталась |
| App | a1awk5bt40 | obs | 2 | 0 | 0 | 2 | 0 | − склеены демо-Output, Key instructions и задача в одно сообщение (ложная посылка «впрыснута вторая задача»); − guard `episode.done` до цикла (мёртв) |
| App | a1awk5bt40 | fix | 2 | 0 | 0 | 2 | 0 | − **удалены Key instructions и настоящая задача** (предложение «remove the trailing second task block»); − guard после ответа (лишний) |

Итого по плечам:

| плечо | сессий | изменений | хорошие | частичные | плохие | хардкод | харнесс сломан | мин |
|---|---|---|---|---|---|---|---|---|
| obs | 8 | 21 | 3 (14%) | 3 | 13 (62%) | 2 | 2 / 8 | 92.7 |
| fix | 8 | 27 | 5 (19%) | 4 | 18 (67%) | 0 | 5 / 8 | 122.2 |

Наблюдения (относительно перебранного):
1. **Качество входа решает больше плеча.** Ложные report (демо-диалог AppWorld принят за эпизод; «выиграл и
   продолжал» в ALFWorld) дают плохие правки в обоих плечах: a1awk5t40, a1awk5bt40, a7awk5ns, a7k5ns — 0 хороших на
   8 сессий. Без трасс редактор проверить их не может; инструкция «an observation may be inaccurate… check what it
   says about src/» помогает только для утверждений о коде (их модель иногда проверяет), не о прогонах.
2. **Шаг вариантов усиливает ложную посылку.** Худший случай фазы — fix a1awk5bt40: один ложный report («вторая
   задача впрыснута») → предложение «remove the trailing second task block» → редактор удалил настоящую задачу и все
   инструкции. obs на том же входе склеил сообщения, но задачу оставил. Предложения превращают гипотезу наблюдения в
   уверенное указание «где и что менять», и редактор fix его исполняет (во вводной fix ему не на что опереться,
   кроме предложения).
3. **Код хуков 9B почти всегда мёртв или ломает.** Из правок кода (хуки, цикл harness.py, extract_code) во всех 16
   сессиях как задумано и без дефектов работают только простые сообщения: «Steps remaining: N of 50» (a1awk5t40
   fix) и напоминание каждый шаг (a1awk5t40 obs, но по ложной посылке); с дефектами — «N steps left» (a7k5ef obs,
   a7k5nf obs/fix) и исполнение всех вызовов хода (a7k5f obs). Остальное мертво или ломает. Типичные ошибки — не то поле ctx (`nb["history"]`, `output`
   вместо `observation`), возврат без `"kind"`, f-строка без `f`, сравнение с первым элементом истории вместо
   предыдущего. Контракт хуков описан в докстринге harness.py, модель его читает, но запустить не может. Хорошие
   правки — почти все в промпте.
4. **Хардкод** — только в obs (2 из 21): пример из конкретного прогона («song genres when the task is about
   playlists») перенесён в промпт. В fix шаг вариантов однажды предложил тот же пример, но редактор его не перенёс.
   2 против 0 — в шуме.
5. **Лимит бенчмарка**: в обоих плечах AppWorld a7awk5f — MAX_STEPS 50 → 100 (fix ещё и пытался править
   bridge.py, отказ). Бездейственно (run.py режет на 50), отмечено как плохая.
6. **Механика edit** держится: 60 из 70 правок применены; отказы — неточная копия (лишний отступ, выдуманный текст
   пустого файла), `same` (модель «забыла» вписать изменение), один `path: None`. Подсказка отказа короткая, модель в
   основной фазе обычно исправляется следующим вызовом (в финале — не успевает).
7. **Траты bash**: несмотря на «code cannot be run (there is no Python)», 15 из 16 сессий редактора хотя бы раз
   пытались запустить python или писать через heredoc (отказов 1–9); a7k5ns obs потеряла на этом всю сессию.

### B1.6 Итог B1 (только относительно перебранного: 4 + 4 входа, по одной сессии на (вход, плечо), T=0.6, один seed)
**Предложение — плечо obs (наблюдения как есть).** Почему:
- по существу плечи не различаются: хороших 3/21 против 5/27, хороших+частичных 6/21 (29%) против 9/27 (33%),
  плохих 62% против 67% — разница в 1–2 правки при одной оценке одной рукой;
- харнесс ломается реже: 2 из 8 сессий против 5 из 8 (fix применяет больше правок — 4.4 против 3.1 на сессию;
  run() в harness.py трогают оба плеча примерно одинаково часто — 5–6 сессий из 8, — но правки кода в fix ломали
  харнесс чаще: падение, обрыв эпизода, подмена ходов хуком); худший исход фазы (удалена задача) — в fix, через шаг вариантов;
- дешевле на ~30% (11.6 против 15.3 мин модели на вход; плюс одна сессия модели вместо двух);
- довод за fix — 0 хардкода против 2 и чуть больше хороших правок в промпте — в шуме.
Главный вывод для метода сильнее выбора плеча: при текущих report и без проверки правок запуском ни одно плечо не
даёт стабильно годных правок (хороших 14–19%). Узкие места — ложные report на входе и код хуков, который 9B не может
проверить.

### B1.7 Время и цена
Пилот p1 (старый промпт): 12.8 + 16.1 + 8.3 = 37 мин. Основные: obs 92.7, fix 122.2 → ≈ 252 мин модели всего; по 2
сессии одновременно, стена 12:15–14:53. check.py — ~20–40 с на сессию, без модели.
Живой замер правок исполнителем **не делал**: оценка цены — ALFWorld ≈ 20 мин стены на вариант (10 игр, 2 потока),
AppWorld ≈ 30 мин на вариант (эпизод ≈ 6 мин); на 1–2 правки каждого плеча ×2 бенчмарка — 1.5–2.5 ч. При базе
AppWorld 3/20 и «нейтральная правка переворачивает 13 из 57 задач» 10 задач не различат малые правки промпта (а
кроме них «лучших» нет: правки кода в основном мертвы или ломают). Счёл не дешёвым и неинформативным.

### B1.8 Что не пробовали
- Локализатор (исследователь → локализатор → редактор) — открытый вопрос дизайна, не строил.
- Проверку правки запуском: инструмент, гоняющий тесты на заглушке / проверяющий форму ответа хуков; редактор без
  Python пишет код вслепую (пункт 3 выше).
- Фильтр входа: только верные report (отделил бы качество редактора от качества входа, но требует разметки —
  загрязнение — или верификатора); редактор fix, видящий и наблюдения, и предложения; редактор по одному наблюдению.
- Повторы сессий, другие seed/T; лимиты (bash 25, бюджет 60, финал 3) — по одному значению; одна итерация настройки
  промпта (после пилота), вторую по итогам основных сессий не делал — сравнение шло на зафиксированных промптах.
- Варианты шага вариантов: число вариантов на наблюдение не задавал (вышло 2–12 предложений на сессию); вывод
  вариантов текстом без инструмента.
- Живой замер исполнителем (B1.7); B2 (число правок и слияние) не трогал.
- Входы a1awk3t40, a7awk5bf, a7awk5nf, a1k5t40, a1k5bt40, a1k5et40, a7k5bf — не брал (по 4 на бенчмарк).

### B1.9 Что не проверено
- Оценка по существу — моя, одна рука, загрязнена (знаю из A1/A7, какие report ложны; читал src и диффы); второго
  читателя нет. Граница «частичная/плохая» и «плохая по ложной посылке» — мой выбор, описан выше.
- Влияние правок на долю решённых задач не измерено ни для одной правки; «хорошая» = правдоподобно помогает.
- Тесты на заглушке ловят падения и изменения формы беседы, но не смысловой вред (удаление задачи нашла только
  сверка слотов, добавленная post hoc; удаление демо тесты видят лишь как «промпт ≠ апстрим»).
- Детерминизм сессий при повторе с тем же seed не проверял.
- Входы — по одной сессии исследователя; разные входы на бенчмарк имеют разное число и качество report (1–8),
  поэтому сравнение по бенчмаркам внутри плеча не делал.
