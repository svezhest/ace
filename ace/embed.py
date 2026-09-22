"""Эмбеддинги BGE-M3 для retrieval-вариантов. Модель грузится при первом вызове."""
import numpy as np

MODEL = "BAAI/bge-m3"
_model = None


def embed(texts):
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(MODEL, device="mps")
    return _model.encode(list(texts), normalize_embeddings=True, convert_to_numpy=True)


def top(query, texts, k):
    """Индексы k ближайших по косинусу."""
    if not texts:
        return []
    q, m = embed([query])[0], embed(texts)
    return list(np.argsort(m @ q)[::-1][:k])
