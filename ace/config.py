"""Настройки стенда: сервер модели, бюджет генерации, seed, размеры выборок и пути.
Всё берётся из окружения."""
import os
from pathlib import Path

OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "http://localhost:8080/v1")
API_KEY = os.getenv("OPENAI_API_KEY", "local")
MODEL = os.getenv("MODEL", "ornith15-9b")
BACKEND = os.getenv("BACKEND", "pydantic-ai")     # доступ к модели: pydantic-ai | wire (ace/model)
MAX_TOKENS = int(os.getenv("MAX_TOKENS", 4096))
SEED = int(os.getenv("SEED", 0))

# размер выборки входит в имя файла данных: formula40.jsonl, formula_train40.jsonl, formula_val10.jsonl
SIZE = int(os.getenv("SIZE", 40))
VAL_SIZE = int(os.getenv("VAL_SIZE", 10))

# протокол задаёт метод; run.py может заменить число проходов и включить офлайн (обучение на train, тест с лучшей по
# val памятью) в одном прогоне
EPOCHS = int(os.getenv("EPOCHS", 0)) or None
OFFLINE = bool(os.getenv("OFFLINE"))

ROOT = Path(__file__).parent.parent
DATA = ROOT / "data"
PROMPTS = Path(__file__).parent / "prompts"
RESULTS = Path(os.getenv("RESULTS", "results"))

# MCE: агенты Claude Agent SDK (model/claude.py) — CLI шлёт /v1/messages в LiteLLM proxy перед сервером модели;
# окружение python агентов — venv апстрима meta-context-engineering; корень workspace (над workspace/<задача>)
CLAUDE_BASE_URL = os.getenv("CLAUDE_BASE_URL", "http://127.0.0.1:4000")
UPSTREAMS = Path(os.getenv("UPSTREAMS", Path.home() / "Projects" / "upstreams"))
MCE_VENV = Path(os.getenv("MCE_VENV", UPSTREAMS / ".venvs" / "mce"))
MCE_ROOT = os.getenv("MCE_ROOT")        # не задан — временная папка на прогон
