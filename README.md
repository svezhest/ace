# ace

Стенд для сравнения методов агентного контекст-инжиниринга (ACE, Dynamic Cheatsheet, SCOPE, TF-GRPO, EvoLib, MCE) на одном цикле. Метод — набор функций `inject / reflect / curate / bound` плюс среда; абляция — замена одной из них.

```
uv venv .venv && uv pip install -p .venv/bin/python openai
python ace/env/sandbox.py --build        # образ docker для исполнения кода
python run.py formula ace 40             # результаты в results/formula40/ace/
python ace/tasks.py meb results/meb40/ace/log.json   # переоценить лог
```

Модель: любой OpenAI-совместимый endpoint (`LOCAL_BASE_URL`, `MODEL`).
