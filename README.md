# ace

Стенд для сравнения методов агентного контекст-инжиниринга (ACE, Dynamic Cheatsheet, SCOPE, TF-GRPO, EvoLib, MCE) на одном цикле. Метод это четыре элемента и решатель:

| Элемент | Что определяет | Модуль |
|---|---|---|
| память | виды записей: класс записи (её поля), операции, срок жизни, скрыт ли от решателя | `ace/memory.py` |
| инжект | что из памяти видит решатель: при запуске, по запросу (каталог), после шага (хук) | `ace/inject.py` |
| сигнал | что после попытки возвращается в систему; отбивка инструмента | `ace/feedback.py` |
| обновление | обработчики событий: шаг (step), задача (reflect), батч из every задач (curate, bound), проход (epoch) | `ace/update.py`, `reflect.py`, `curate.py`, `bound.py` |
| решатель | среда задачи, число попыток, температура, голосование, перспективы, формат ответа | `ace/loop.py` |

Метод — только сборка: параметры, промпты апстрима файлами (`ace/methods/prompts/`, `ace/prompts.py`) и блоки
библиотеки. Код любого уровня лежит в модуле этого уровня рядом с остальными вариантами, даже если пока
его использует один метод:

| Где | Блоки |
|---|---|
| память `memory.py` | схема вид -> `Kind(класс записи, ops, per="task", private)`; записи `Note`, `Bullet` (ACE), `Rule` (SCOPE), `Pair` (DC-RS), `Entry` (прототип), `Skill`, `Insight`, `Solution` (EvoLib), `Iteration` (MCE); `needs` — что блок требует от памяти, сверяется при сборке метода; `perspectives`, `slug` |
| инжект `inject.py` | `show(kinds, pick, line/layout, before, empty, head)`; pick: `topk` (запрос — вопрос или ошибка шага), `sample` (`gain_weight`), `where`; line: `plain`, `dashed`, `numbered`, `dotted`, `counted`, `prefixed`; layout: `by_group(line, поле)`, `sections`, `pairs`; `choose`, `concat`, `synth`, `fixed`, `catalog`; `hooked(base, hook, on)`, `on_failure` |
| сигнал `feedback.py` | `Feedback(verdict: golden / yes_no / judge / majority / none, usage: env / self / none)` |
| общие `update.py` | `Update(reflect, curate, bound, every, step, epoch)`; `at_once` (шаг: reflect и curate без батча), `flush`, `chain`; `ask` (вызов модели: промпт, поля, схема, parse, then), `paired`, `seq`, `when`, `maybe`, `on_prev`, `retry` |
| разбор `parse.py` | `opened`, `enclosed`, `between`, `fenced`, `json_block`, `subtasks`, `counted_line` |
| reflect `reflect.py` | обёртки `keep`, `rounds`, `on_answer`, `on_tool`, `perspectives`, `best_of`, `each_attempt`; поля, схемы и then: уроки ACE стенда и прототипа, диагноз ACE, правило на шаг SCOPE, групповое преимущество TF-GRPO, IG EvoLib, cheatsheet DC |
| curate `curate.py` | обёртки `each`, `per_lesson`, `admit`, `limit`, `planned`, `chain`; правки `count`, `add`, `apply_ops`, `remember`, `rewrite`, `tools`, `consolidate`; поля, схемы и then: плейбук ACE, классификатор SCOPE, план батча TF-GRPO, библиотека EvoLib, итерации MCE, операции прототипа |
| bound `bound.py` | `prune`, `budget`, `gate`, `merge_similar` (`merge_counted`), `optimize` (`rule_optimizer` SCOPE), `chain`; конец прохода: `best_by_val` |

Абляция это замена одной части: `swap(ace, inject=inject.catalog())` или `swap(ace, curate=...)`.
Новый метод — новая сборка; если блока не хватает, существующий делится на два.

```
uv venv .venv && uv pip install -p .venv/bin/python "pydantic-ai-slim[openai]"
python ace/env/sandbox.py --build        # образ docker для исполнения кода
python run.py formula ace 40             # результаты в results/formula40/ace/
EPOCHS=3 OFFLINE=1 python run.py formula mce 40   # офлайн: обучение на train, тест с лучшей по val памятью
python ablate.py formula 40              # вся цепочка абляций, или список ступеней после N
python report.py                         # таблица по results/
python ace/tasks.py meb results/meb40/ace/log.json   # переоценить лог
```

Методы (`ace/methods/`): baseline; dc, dc_rs и контроли dc_retrieval, dc_history, dc_code; ace (вариант стенда),
ace_exact и ace_exact_dedup (как в апстриме); scope, scope_code (с исполнением python), scope_bo2, scope_k2; tfgrpo;
evolib, evolib_judge; mce; proto. Гибриды (`hybrids.py`): ace_bo2, ace_group, ace_opt, proto_opt, ace_hooks, proto_hooks и proto_hooks_raw (хуки по ошибкам инструментов: уроки моделью или из траектории, счётчики исходов).
В docstring каждого метода: что взято из апстрима (файлы) и где расходимся. Retrieval-варианты считают эмбеддинги BGE-M3 (`ace/embed.py`). Ступени абляции в `ablate.py`.
Окружение: `LOCAL_BASE_URL`, `MODEL`, `MAX_TOKENS` (MEB: 8192), `SEED`.
