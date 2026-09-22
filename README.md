# ace

Стенд для сравнения методов агентного контекст-инжиниринга (ACE, Dynamic Cheatsheet, SCOPE, TF-GRPO, EvoLib, MCE) на одном цикле. Метод это четыре элемента и решатель:

| Элемент | Что определяет | Модуль |
|---|---|---|
| память | виды записей и разрешённые операции | `ace/memory.py` |
| инжект | что из памяти видит решатель | `ace/inject.py` |
| сигнал | что после попытки возвращается в систему | `ace/feedback.py` |
| обновление | reflect, curate, bound, раз в every задач | `ace/update.py` |
| решатель | среда задачи, число попыток, голосование, перспективы | `ace/loop.py` |

Абляция это замена одной части: `swap(ace, inject=inject.catalog())` или `swap(ace, curate=...)`.

```
uv venv .venv && uv pip install -p .venv/bin/python "pydantic-ai-slim[openai]"
python ace/env/sandbox.py --build        # образ docker для исполнения кода
python run.py formula ace 40             # результаты в results/formula40/ace/
python ablate.py formula 40              # вся цепочка абляций, или список ступеней после N
python report.py                         # таблица по results/
python ace/tasks.py meb results/meb40/ace/log.json   # переоценить лог
```

Методы: baseline, dc, dc_rs, ace, scope, scope_k2, tfgrpo, evolib, mce, proto (`ace/methods/`). Retrieval-варианты считают эмбеддинги BGE-M3 (`ace/embed.py`). Ступени абляции в `ablate.py`.
Окружение: `LOCAL_BASE_URL`, `MODEL`, `MAX_TOKENS` (MEB: 8192), `SEED`.
