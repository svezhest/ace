"""Эмбеддинги BGE-M3 для retrieval-вариантов. Модель грузится при первом вызове."""
MODEL = "BAAI/bge-m3"
_model = None


def embed(texts):
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(MODEL, device="mps")
    return _model.encode(list(texts), normalize_embeddings=True, convert_to_numpy=True)

