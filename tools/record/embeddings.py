"""OpenAI-совместимый /v1/embeddings на BGE-M3, для апстримов, которые зовут эмбеддинги по API
(EvoLib: text-embedding-3-small), — у шлюза модели их нет:
    uv run python -m tools.record.embeddings [--port 8092]
Имя модели в запросе не проверяется. Векторы нормированы, float32; encoding_format "base64" (его по умолчанию
шлёт клиент openai) — байты float32 little-endian, иначе списком чисел. Запись: record.py --embeddings-upstream
http://127.0.0.1:8092."""
import argparse
import base64
import os
from functools import cache
from http.server import ThreadingHTTPServer

import numpy as np

from tools.record.record import EMBEDDINGS, Handler

MODEL = "BAAI/bge-m3"


@cache
def model():
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(MODEL, device=os.getenv("EMBED_DEVICE"))


def embed(texts):
    return model().encode(list(texts), normalize_embeddings=True, convert_to_numpy=True)


def response(body):
    texts = body["input"]
    if isinstance(texts, str):
        texts = [texts]
    vectors = np.asarray(embed(texts), dtype="<f4")
    b64 = body.get("encoding_format") == "base64"
    data = [{"object": "embedding", "index": i,
             "embedding": base64.b64encode(v.tobytes()).decode() if b64 else v.tolist()}
            for i, v in enumerate(vectors)]
    return {"object": "list", "data": data, "model": body.get("model", MODEL),
            "usage": {"prompt_tokens": 0, "total_tokens": 0}}


class Embedder(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, addr):
        super().__init__(addr, Handler)

    def answer(self, path, body, out):
        if path != EMBEDDINGS:
            return out.error(404, f"only {EMBEDDINGS}")
        out.reply(200, response(body), body)

    def get(self, out):
        out.error(404, f"only {EMBEDDINGS}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8092)
    srv = Embedder(("127.0.0.1", ap.parse_args().port))
    print(f"listening on http://127.0.0.1:{srv.server_address[1]}/v1", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
