"""Эмбеддинги для retrieval-вариантов: BGE-M3 (модель грузится при первом вызове) или готовые эмбеддинги апстрима для
вопросов его бенчмарка (data/<задача>_embeddings.csv — строки embeddings/<task>.csv апстрима: input, tokens,
embedding; какие есть — решают данные, а не код)."""
import csv
import json
from functools import cache

from . import config

MODEL = "BAAI/bge-m3"
CSV_FIELD_LIMIT = 1 << 30   # вектор в строке csv длиннее предела поля по умолчанию


@cache
def model():
    """BGE-M3, загружается при первом вызове."""
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(MODEL, device=config.EMBED_DEVICE)


def embed(texts):
    return model().encode(list(texts), normalize_embeddings=True, convert_to_numpy=True)


@cache
def table():
    """Готовые эмбеддинги апстримов из data/*_embeddings.csv: вопрос -> вектор."""
    csv.field_size_limit(CSV_FIELD_LIMIT)
    out = {}
    for path in sorted(config.DATA.glob("*_embeddings.csv")):
        with open(path, newline="") as f:
            for row in csv.DictReader(f):
                out[row["input"]] = json.loads(row["embedding"])
    return out


def similarity(texts, query):
    """Косинус query с каждым из texts. Если у всех готовые эмбеддинги апстрима — по ним и cosine_similarity, как в
    апстриме DC (language_model.py:510); иначе BGE-M3."""
    known = table()
    if query in known and all(t in known for t in texts):
        from sklearn.metrics.pairwise import cosine_similarity
        return cosine_similarity([known[query]], [known[t] for t in texts])[0]
    return embed(texts) @ embed([query])[0]
