# ace

Стенд для сравнения методов агентного контекст-инжиниринга (ACE, Dynamic Cheatsheet, SCOPE, TF-GRPO, EvoLib, MCE) на
одном цикле. Метод — ученик, собранный из уровней; цикл один на все методы и зовёт хуки ученика на своих масштабах
(шаг / попытка / вопрос / батч / проход). Устройство — [docs/architecture.md](docs/architecture.md).

| уровень | модуль |
|---|---|
| доступ к модели: `Call(messages, params, reader)`, бэкенды pydantic-ai и провод апстрима (openai) | `ace/model/` |
| попытки и в зачёт (first / vote / best = pass@k) | `ace/loop.py` |
| вердикт попытки и группы | `ace/verdict.py` |
| извлечение | `ace/extract/<метод>.py` |
| память | `ace/memory/<метод>.py` (контейнеры — `lessons.py`, `documents.py`) |
| показ | `ace/show/<метод>.py` (общие варианты — `ace/show/__init__.py`) |
| когда учится, сборка (`Learner`, `swap`) | `ace/learner.py` |
| среда попытки (песочница) | `ace/env/` |
| мета: Gate, Meta (MCE), Hooks | `ace/wrap/` |

Методы (`ace/methods/<метод>.py` — только сборка, в docstring — что метод берёт на каждом уровне): baseline;
ace, ace_text, ace_rewrite (стенд), ace_exact и ace_exact_dedup (как в апстриме), ace_exact_used; dc, dc_code, dc_rs, dc_retrieval,
dc_history; scope, scope_bo2, scope_code, scope_k2; tfgrpo; evolib, evolib_judge; mce, mce_fs, mce_ace; гибриды ace_bo2,
ace_opt, ace_hooks, ace_group. По умолчанию уровни ведут себя как апстрим; неустранимые отличия —
[DEVIATIONS.md](DEVIATIONS.md), верность — тесты-мостик `tests/bridge/` (эталоны сняты с апстримов, `bridge/`)
и воспроизведение записей апстримов на живой модели `tests/live/` (`bridge/live/<метод>/`).
Прототип отложен: его код — в теге `pre-rewrite` (`git show pre-rewrite:ace/methods/proto.py`).

```
uv sync                                   # окружение с зависимостями для разработки (pytest)
docker build -t cestand-sandbox ace/env   # образ docker для исполнения кода
uv run python run.py formula ace 40       # результаты в results/formula40/ace/
EPOCHS=3 OFFLINE=1 uv run python run.py formula ace 40   # офлайн: обучение на train, тест с лучшей по val памятью
BACKEND=wire uv run python run.py formula dc 40          # вызовы без инструментов — клиентом openai как есть
uv run python ablate.py formula 40        # цепочка абляций; ступени по именам: ablate.py formula 40 ace ace_opt
uv run python report.py                   # таблица по results/
uv run pytest -q                          # тесты, в том числе мостик к апстримам (tests/bridge)
uv run python tools/trace.py /tmp/a.json   # снимок запросов всех методов на фиктивной модели
uv run python tools/compare.py /tmp/a.json /tmp/b.json   # два снимка: что поменяла правка
```

Настройки (`ace/config.py`, из окружения): `OPENAI_BASE_URL` (по умолчанию `http://localhost:8080/v1`),
`OPENAI_API_KEY` (`local`), `MODEL`, `BACKEND` (`pydantic-ai` или `wire`), `MAX_TOKENS` (MEB: 8192), `SEED`, размеры
выборок `SIZE` и `VAL_SIZE` (40 и 10, входят в имя файла данных), `EPOCHS`, `OFFLINE`, `RESULTS`.

## Абляции и замеры

`ablate.py` — цепочка замен по уровням: каждая ступень меняет один уровень относительно предыдущей ступени
или базы своего блока (в комментарии у ступени — что меняется и от чего).

| блок | ступени |
|---|---|
| контроли | baseline; placebo (показ: текст той же длины без знаний); sc3 (3 попытки, T = 0 и 0.7, голосование — столько же вызовов, сколько у ace, без памяти) |
| методы | ace_exact, dc, scope, tfgrpo, evolib, mce — как в апстримах, строки для сравнения |
| база | ace — рефлектор с метками, куратор операциями, отсев вредных, показ всего |
| извлечение | ace_text (свободный текст; память без отсева — иначе стык не сойдётся), ace_bo2 (Best-of-2), ace_group (контраст TF-GRPO по группе из 3, куратор ACE) |
| память | ace_opt (предел 10 с оптимизатором SCOPE вместо отсева), ace_rewrite (перезапись куратором) |
| показ | ace_catalog (каталог + read); ace_code (среда с python) -> ace_hooks (урок после ошибки в конец истории) и ace_hooks_system (хуки в системном промпте с начала) |
| мета | ace_e3 (3 прохода) -> mce_ace (MCE над ACE) |
| вердикт | evolib (голосование) -> evolib_judge (судья) -> evolib_golden (верный ответ) |
| попытки | evolib_n5 (5 попыток вместо 3), evolib_t07 (попытки различаются и температурой) |
| показ посреди попытки | scope_code (правило на шаге переписывает системный промпт, как в апстриме) -> scope_append (дописывается в конец истории) |

`report.py`: верно, обрывы, вызовы, токены; `*` у верных — зачёт pass@k (scope_k2), а не точность; для
каталога — доля вопросов с чтением записей и точность с чтением и без; для хуков — сколько раз хук показан
(fired) и сколько раз помог.

Замеры механизмов (`scripts/`, итоги в `results/TASKN/`):

```
uv run python scripts/evolib_ig.py formula 40     # IG по вопросам при голосовании, судье и верном ответе
uv run python scripts/scope_patch.py formula 40   # перезапись системного промпта против дописывания
uv run python scripts/ace_labels.py formula 40    # ace_exact_used: сколько названных пунктов и меток доходит до счётчиков
```

- `evolib_ig.py` — по каждому вопросу ответы попыток, голос, баллы и IG (`ig.json`); таблица IG по числу
  разных ответов группы и по числу верных попыток: без метки IG — мера разногласия (все совпали 0, 2 из 3
  ≈ 0.41, все разные ≈ 1.10), а не правильности.
- `scope_patch.py` — точность, вызовы, токены промпта, попытки с правилами на шаге и точность с ними и без.
- `ace_labels.py` — по раундам рефлектора: id, названные решателем в USED, распознанные нашим разбором и
  регуляркой апстрима (core/generator.py:115, переложена на наши id: только в скобках), метки рефлектора
  и сколько из них попало в счётчики.
