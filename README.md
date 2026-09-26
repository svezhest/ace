# ace

Стенд для сравнения методов агентного контекст-инжиниринга (ACE, Dynamic Cheatsheet, SCOPE, TF-GRPO, EvoLib, MCE, GEPA) на
одном цикле. Метод — ученик, собранный из уровней; цикл один на все методы и зовёт хуки ученика на своих масштабах
(шаг / попытка / вопрос / батч / проход). Устройство — [docs/architecture.md](docs/architecture.md).

| уровень | модуль |
|---|---|
| доступ к модели: `Call(messages, params, reader)`, бэкенды pydantic-ai и провод апстрима (openai) | `ace/model/` |
| попытки и в зачёт (first / vote / best = pass@k) | `ace/loop.py` |
| вердикт попытки и группы | `ace/verdict.py` |
| извлечение | `ace/extract/<метод>.py` |
| память | `ace/memory/<метод>.py` (контейнеры — `lessons.py`, `documents.py`) |
| решатель: общий или решатель апстрима метода (`learner.solver`) | `ace/solver/<метод>.py` |
| показ (у общего решателя) | `ace/show/` |
| когда учится, сборка (`Learner`, `swap`) | `ace/learner.py` |
| среда попытки (песочница) | `ace/env/` |
| мета: Gate, Meta (MCE), Evolution (GEPA: пул и Парето-выбор), Hooks | `ace/wrap/` |

Методы (`ace/methods/<метод>.py` — только сборка, в docstring — что метод берёт на каждом уровне): baseline;
ace и ace_dedup (как в апстриме), ace_used; ace_stand, ace_stand_text, ace_stand_rewrite (стенд); dc, dc_code, dc_rs, dc_retrieval,
dc_history; scope, scope_bo2, scope_code, scope_k2; tfgrpo; evolib, evolib_judge; mce, mce_fs, mce_ace_stand; gepa; гибриды ace_stand_bo2,
ace_stand_opt, ace_stand_hooks, ace_stand_group. По умолчанию уровни ведут себя как апстрим; неустранимые отличия —
[DEVIATIONS.md](DEVIATIONS.md), верность — тесты-мостик `tests/bridge/` (эталоны сняты с апстримов, `bridge/`)
и воспроизведение записей апстримов на живой модели `tests/live/` (`bridge/live/<метод>/`).
Прототип отложен: его код — в теге `pre-rewrite` (`git show pre-rewrite:ace/methods/proto.py`).

```
uv sync                                   # окружение с зависимостями для разработки (pytest)
docker build -t cestand-sandbox ace/env   # образ docker для исполнения кода
uv run python run.py formula ace 40       # в results/formula40/ace/online-w15-e1_<модель>_<бэкенд>/
EPOCHS=3 OFFLINE=1 uv run python run.py formula ace_stand 40   # другой протокол в этом прогоне: офлайн, 3 прохода
BACKEND=wire uv run python run.py formula dc 40          # вызовы без инструментов — клиентом openai как есть
uv run python ablate.py formula 40        # цепочка абляций; ступени по именам: ablate.py formula 40 ace_stand ace_stand_opt
uv run python report.py                   # таблица по results/
uv run pytest -q                          # тесты, в том числе мостик к апстримам (tests/bridge)
uv run python -m tools.trace /tmp/a.json   # снимок запросов всех методов на фиктивной модели
uv run python tools/compare.py /tmp/a.json /tmp/b.json   # два снимка: что поменяла правка
```

Настройки (`ace/config.py`, из окружения): `OPENAI_BASE_URL` (по умолчанию `http://localhost:8080/v1`),
`OPENAI_API_KEY` (`local`), `MODEL`, `BACKEND` (`pydantic-ai` или `wire`), `MAX_TOKENS` (MEB: 8192), `SEED`, размеры
выборок `SIZE` и `VAL_SIZE` (40 и 10, входят в имя файла данных), `RESULTS`. Протокол (онлайн / офлайн, проходы,
окно ACE) задаёт метод по своему апстриму (`learner.protocol`); `EPOCHS` и `OFFLINE` меняют его только в одном
прогоне `run.py`, `ablate.py` гоняет каждую ступень по её протоколу.

## Абляции и замеры

`ablate.py` — цепочка замен по уровням: каждая ступень меняет один уровень относительно предыдущей ступени
или базы своего блока (в комментарии у ступени — что меняется и от чего).

| блок | ступени |
|---|---|
| контроли | baseline; placebo (показ: текст той же длины без знаний); sc3 (3 попытки, T = 0 и 0.7, голосование — столько же вызовов, сколько у ace_stand, без памяти) |
| методы | ace, dc, scope, tfgrpo, evolib, mce, gepa — как в апстримах, строки для сравнения |
| база | ace_stand — рефлектор с метками, куратор операциями, отсев вредных, показ всего |
| извлечение | ace_stand_text (свободный текст; память без отсева — иначе стык не сойдётся), ace_stand_bo2 (Best-of-2), ace_stand_group (контраст TF-GRPO по группе из 3, куратор ACE) |
| память | ace_stand_opt (предел 10 с оптимизатором SCOPE вместо отсева), ace_stand_rewrite (перезапись куратором) |
| показ и среда | ace_stand_catalog (каталог + read); ace_stand_code (среда с python) -> ace_stand_code_attempt (контейнер на попытку) и ace_stand_hooks (урок после ошибки исполнения в конец истории) -> ace_stand_hooks_system (хуки в системном промпте с начала), ace_stand_hooks_raw (урок без модели: ошибка и следующий прошедший вызов) |
| мета | ace_stand_gate (правка батча остаётся, только если на val не хуже); ace_stand_e3 (офлайн, 3 прохода) -> mce_ace_stand (MCE над ACE) |
| вердикт | evolib (голосование) -> evolib_judge (судья) -> evolib_golden (верный ответ) |
| попытки | evolib_n5 (5 попыток вместо 3), evolib_t07 (попытки различаются и температурой — параметр решателя EvoLib) |
| показ посреди попытки | scope_code (правило на шаге переписывает системный промпт, как в апстриме) -> scope_append (дописывается в конец истории) |

`report.py`: верно, обрывы, вызовы, токены; `*` у верных — зачёт pass@k (scope_k2), а не точность; для
каталога — доля вопросов с чтением записей и точность с чтением и без; для хуков — сколько раз хук показан
(fired) и сколько раз помог.

Замеры механизмов (`scripts/`, итоги в `results/TASKN/`):

```
uv run python scripts/evolib_ig.py formula 40     # IG по вопросам при голосовании, судье и верном ответе
uv run python scripts/scope_patch.py formula 40   # перезапись системного промпта против дописывания
uv run python scripts/ace_labels.py formula 40    # ace_used: сколько названных пунктов и меток доходит до счётчиков
```

- `evolib_ig.py` — по каждому вопросу ответы попыток, голос, баллы и IG (`ig.json`); таблица IG по числу
  разных ответов группы и по числу верных попыток: без метки IG — мера разногласия (все совпали 0, 2 из 3
  ≈ 0.41, все разные ≈ 1.10), а не правильности.
- `scope_patch.py` — точность, вызовы, токены промпта, попытки с правилами на шаге и точность с ними и без.
- `ace_labels.py` — по раундам рефлектора: id, названные решателем в USED, распознанные нашим разбором и
  регуляркой апстрима (core/generator.py:115, переложена на наши id: только в скобках), метки рефлектора
  и сколько из них попало в счётчики.
