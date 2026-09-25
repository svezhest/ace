"""Эмбеддинги для retrieval-вариантов: BGE-M3 (модель грузится при первом вызове) или готовые эмбеддинги апстрима
DC для вопросов его бенчмарков (data/<задача>_embeddings.csv — строки embeddings/<task>.csv апстрима: input, tokens,
embedding)."""
import csv
import json

from . import config

MODEL = "BAAI/bge-m3"
TABLES = ("meb",)           # задачи, для вопросов которых у DC есть готовые эмбеддинги
_model = None
_table = None


def embed(texts):
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(MODEL, device="mps")
    return _model.encode(list(texts), normalize_embeddings=True, convert_to_numpy=True)


def table():
    """Готовые эмбеддинги апстрима DC: вопрос -> вектор."""
    global _table
    if _table is None:
        csv.field_size_limit(1 << 30)
        _table = {}
        for task in TABLES:
            with open(config.DATA / f"{task}_embeddings.csv", newline="") as f:
                _table.update((r["input"], json.loads(r["embedding"])) for r in csv.DictReader(f))
    return _table


def similarity(texts, query):
    """Косинус query с каждым из texts. Если у всех готовые эмбеддинги апстрима DC — по ним и cosine_similarity,
    как в апстриме (language_model.py:510); иначе BGE-M3."""
    known = table()
    if query in known and all(t in known for t in texts):
        from sklearn.metrics.pairwise import cosine_similarity
        return cosine_similarity([known[query]], [known[t] for t in texts])[0]
    return embed(texts) @ embed([query])[0]
