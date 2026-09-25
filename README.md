# ace

Стенд для сравнения методов агентного контекст-инжиниринга (ACE, Dynamic Cheatsheet, SCOPE, TF-GRPO, EvoLib, MCE) на одном цикле.
Метод — ученик, собранный из уровней; цикл один на все методы и зовёт хуки ученика на своих масштабах
(шаг / попытка / вопрос / батч / проход). Устройство — [docs/architecture.md](docs/architecture.md).

| уровень | что решает | модуль |
|---|---|---|
| попытки и в зачёт | сколько попыток, чем различаются, чей ответ считается (first / greedy / vote / best = pass@k) | `ace/loop.py` |
| вердикт попытки / группы | golden / yes_no / judge / none; vote / none; верный ответ в эпизоде только при golden | `ace/verdict.py` |
| извлечение | группа попыток -> уроки, баллы и объявленные добавки (labels, confidence, ...) | `ace/extract/` |
| память | уроки (записи со статистикой, операции ADD / UPDATE = новая запись / DELETE) или документы (файлы, `ace/fs.py`) | `ace/memory/` |
| показ | что видит решатель: весь текст, каталог с read, top-k, выборка по весу, ветки, синтез, урок после ошибки (`Patch`) | `ace/show.py` |
| когда учится | раз в `every` вопросов, `flush` неполного батча | `ace/learner.py` |
| среда попытки | песочница: контейнер на вызов или на попытку | `ace/env/` |

Сборка — `ace/learner.py` (`Learner`, `swap`); единственный проверяемый стык: память требует добавки от
извлечения (`requires`), извлечение их даёт (`gives`). Абляция — замена уровня: `swap(ace, "ace_text",
extract=Reflector(free=True), memory=Playbook(prune=None))`. Вмешательство посреди попытки — `Patch` из
`on_step` (`ace/model.py`): переписать системный промпт, дописать сообщение в конец истории или к результату
инструмента. Промпты — шаблоны Jinja2 в `ace/prompts/`, сериализации для модели — `ace/render.py`,
разбор ответов — `ace/parse.py`, настройки — `ace/config.py`.

Методы (`ace/methods/`): baseline; ace (стенд: рефлектор с метками, куратор операциями, отсев), ace_text,
ace_rewrite; ace_exact и ace_exact_dedup (как в апстриме). В docstring метода — что взято из апстрима и где
расходимся; все отклонения — в [DEVIATIONS.md](DEVIATIONS.md).
DC (`ace/methods/dc.py`): dc (DC-Cu: cheatsheet целиком, куратор переписывает), dc_code (с песочницей,
контейнер на вызов), dc_rs (пары и синтез cheatsheet под вопрос), контроли dc_retrieval и dc_history.
TF-GRPO (`ace/methods/tfgrpo.py`, извлечение `ace/extract/tfgrpo.py`):
в зачёт итоговый агент (T = 0.3, top_p 0.95), группа из 5 при T = 0.7, контраст попыток, план батча раз в 20.
EvoLib (`ace/methods/evolib.py`, извлечение `ace/extract/evolib.py`): evolib (3 попытки, различие — выборка
памяти по весу, в зачёт и вердикт группы — голосование; библиотека skills / insights с IG и Future IG,
слиянием похожих и скрытым лучшим решением вопроса) и evolib_judge (баллы от судьи).

Прототип отложен: его старый код — в теге `pre-rewrite` (`git show pre-rewrite:ace/methods/proto.py`).

```
uv sync                                   # окружение с зависимостями для разработки (pytest)
docker build -t cestand-sandbox ace/env   # образ docker для исполнения кода
uv run python run.py formula ace 40       # результаты в results/formula40/ace/
EPOCHS=3 OFFLINE=1 uv run python run.py formula ace 40   # офлайн: обучение на train, тест с лучшей по val памятью
uv run python ablate.py formula 40        # цепочка абляций; ступени по именам: ablate.py formula 40 ace ace_opt
uv run python report.py                   # таблица по results/
uv run pytest -q                          # тесты; старые логи results/ переигрываются проверками задач
uv run python tools/trace.py /tmp/t.json && uv run python tools/compare.py tools/ref_variants.json /tmp/t.json
                                          # трасса промптов против старого кода (DEVIATIONS.md)
uv run python tools/as_old.py /tmp/o.json && uv run python tools/compare.py /tmp/o.json
                                          # то же с настройками старого кода там, где решено иначе
```

Настройки (`ace/config.py`, из окружения): `OPENAI_BASE_URL` (по умолчанию `http://localhost:8080/v1`; старое
`LOCAL_BASE_URL` тоже читается), `OPENAI_API_KEY` (`local`), `MODEL`, `MAX_TOKENS` (MEB: 8192), `SEED`, размеры
выборок `SIZE` и `VAL_SIZE` (40 и 10, входят в имя файла данных), `EPOCHS`, `OFFLINE`, `RESULTS`.

Перенесены на уровни (поток B): scope, scope_bo2, scope_code, scope_k2 (`ace/methods/scope.py`, правило на шаг —
`ace/extract/scope.py`); mce = Meta(базовый агент с файлами) и mce_ace = Meta(ACE) (`ace/methods/mce.py`);
обёртки Meta и Gate (`ace/wrap.py`), Hooks — хуки по ошибкам (`ace/hooks.py`); гибриды ace_bo2, ace_opt, ace_hooks
(`ace/methods/hybrids.py`). ace_group — после переноса TF-GRPO.

## Абляции и замеры

`ablate.py` — цепочка замен по уровням: каждая ступень меняет один уровень относительно предыдущей ступени
или базы своего блока (в комментарии у ступени — что меняется и от чего).

| блок | ступени |
|---|---|
| контроли | baseline; placebo (показ: текст той же длины без знаний); sc3 (3 попытки, T = 0 и 0.7, голосование — столько же вызовов, сколько у ace, без памяти) |
| методы | ace_exact, dc, scope, tfgrpo, evolib, mce — как в апстримах, строки для сравнения |
| база | ace — рефлектор с метками, куратор операциями, отсев вредных, показ всего |
| извлечение | ace_text (свободный текст; память без отсева — иначе стык не сойдётся), ace_bo2 (Best-of-2), ace_group (появится в реестре — войдёт в цепочку) |
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
uv run python scripts/ace_labels.py formula 40    # ace_exact: сколько названных пунктов и меток доходит до счётчиков
```

- `evolib_ig.py` — по каждому вопросу ответы попыток, голос, баллы и IG (`ig.json`); таблица IG по числу
  разных ответов группы и по числу верных попыток: без метки IG — мера разногласия (все совпали 0, 2 из 3
  ≈ 0.41, все разные ≈ 1.10), а не правильности.
- `scope_patch.py` — точность, вызовы, токены промпта, попытки с правилами на шаге и точность с ними и без.
- `ace_labels.py` — по раундам рефлектора: id, названные решателем в USED, распознанные нашим разбором и
  регуляркой апстрима (core/generator.py:115, переложена на наши id: только в скобках), метки рефлектора
  и сколько из них попало в счётчики.
