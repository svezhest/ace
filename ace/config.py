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

# протокол run.py: проходов по train и офлайн-режим (обучение на train, тест с лучшей по val памятью)
EPOCHS = int(os.getenv("EPOCHS", 0)) or None
OFFLINE = bool(os.getenv("OFFLINE"))

ROOT = Path(__file__).parent.parent
DATA = ROOT / "data"
PROMPTS = Path(__file__).parent / "prompts"
RESULTS = Path(os.getenv("RESULTS", "results"))
