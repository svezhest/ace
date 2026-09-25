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

**Идёт переписывание.** SCOPE, TF-GRPO, EvoLib, MCE, прототип, хуки по ошибкам и гибриды ещё не
перенесены на уровни: их старый код — в коммите 2c5433e (`git show 2c5433e:ace/methods/scope.py`) и в теге
`pre-rewrite`. `ablate.py` пока не работает (импортирует старые методы).

```
uv sync                                   # окружение с зависимостями для разработки (pytest)
docker build -t cestand-sandbox ace/env   # образ docker для исполнения кода
uv run python run.py formula ace 40       # результаты в results/formula40/ace/
EPOCHS=3 OFFLINE=1 uv run python run.py formula ace 40   # офлайн: обучение на train, тест с лучшей по val памятью
uv run python report.py                   # таблица по results/
uv run pytest -q                          # тесты; старые логи results/ переигрываются проверками задач
uv run python tools/trace.py /tmp/t.json && uv run python tools/compare.py tools/ref_variants.json /tmp/t.json
                                          # трасса промптов против старого кода (DEVIATIONS.md)
```

Настройки (`ace/config.py`, из окружения): `OPENAI_BASE_URL` (по умолчанию `http://localhost:8080/v1`; старое
`LOCAL_BASE_URL` тоже читается), `OPENAI_API_KEY` (`local`), `MODEL`, `MAX_TOKENS` (MEB: 8192), `SEED`, размеры
выборок `SIZE` и `VAL_SIZE` (40 и 10, входят в имя файла данных), `EPOCHS`, `OFFLINE`, `RESULTS`.
