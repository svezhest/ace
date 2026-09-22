# ace

Стенд для сравнения методов агентного контекст-инжиниринга (ACE, Dynamic Cheatsheet, SCOPE, TF-GRPO, EvoLib, MCE) на одном цикле. Метод — набор функций `inject / reflect / curate / bound` плюс среда; абляция — замена одной из них.

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
