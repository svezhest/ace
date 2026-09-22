# ace

Стенд для сравнения методов агентного контекст-инжиниринга (ACE, Dynamic Cheatsheet, SCOPE, TF-GRPO, EvoLib, MCE) на одном цикле. Метод это четыре элемента и решатель:

| Элемент | Что определяет | Модуль |
|---|---|---|
| память | виды записей и разрешённые операции | `ace/memory.py` |
| инжект | что из памяти видит решатель | `ace/inject.py` |
| сигнал | что после попытки возвращается в систему | `ace/feedback.py` |
| обновление | reflect, curate, bound, раз в every задач | `ace/update.py`, `reflect.py`, `curate.py`, `bound.py` |
| решатель | среда задачи, число попыток, температура, голосование, перспективы, формат ответа | `ace/loop.py` |

Метод — сборка из блоков плюс промпты апстрима файлами (`ace/methods/prompts/`, `ace/prompts.py`):

| Где | Блоки |
|---|---|
| память | схема вид -> операции; `Kind(ops, per="task")` — записи на одну задачу; поле `group` (раздел, домен) |
| инжект | `show(kinds, pick, line/layout, before, empty, head)`; pick: `topk`, `sample`, `where`; `by_group`; `choose`, `concat`, `synth`, `fixed`, `catalog` |
| сигнал | `Feedback(verdict: golden / yes_no / judge / majority / none, usage: env / self / none)` |
| общие | `ask` (вызов модели по промпту), `seq`, `when`, `maybe`, `retry` |
| reflect | `keep`, `rounds`, `per_step`, `perspectives`, `best_of`, `each_attempt`, `log_gain`, `future_gain` |
| curate | `each`, `per_lesson`, `count`, `add`, `apply_ops`, `remember`, `rewrite`, `tools`, `admit`, `limit`, `consolidate`, `duplicate_words` |
| bound | `prune`, `budget`, `gate`, `merge_similar`, `best_by_val`, `chain`; `optimize` SCOPE |

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
ace_exact и ace_exact_dedup (как в апстриме); scope, scope_bo2, scope_k2; tfgrpo; evolib, evolib_judge; mce; proto.
В docstring каждого метода: что взято из апстрима (файлы) и где расходимся. Retrieval-варианты считают эмбеддинги BGE-M3 (`ace/embed.py`). Ступени абляции в `ablate.py`.
Окружение: `LOCAL_BASE_URL`, `MODEL`, `MAX_TOKENS` (MEB: 8192), `SEED`.
