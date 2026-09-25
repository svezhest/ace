"""OpenAI-совместимый /v1/embeddings на BGE-M3 стенда (ace.embed), для апстримов, которые зовут эмбеддинги по API
(EvoLib: text-embedding-3-small), — у шлюза модели их нет:
    uv run python -m tools.record.embeddings [--port 8092]
Имя модели в запросе не проверяется. Векторы нормированы, float32; encoding_format "base64" (его по умолчанию
шлёт клиент openai) — байты float32 little-endian, иначе списком чисел. Запись: record.py --embeddings-upstream
http://127.0.0.1:8092."""
import argparse
import base64

import numpy as np

from ace import embed
from tools.record import wire


def response(body):
    texts = body["input"]
    if isinstance(texts, str):
        texts = [texts]
    vectors = np.asarray(embed.embed(texts), dtype="<f4")
    b64 = body.get("encoding_format") == "base64"
    data = [{"object": "embedding", "index": i,
             "embedding": base64.b64encode(v.tobytes()).decode() if b64 else v.tolist()}
            for i, v in enumerate(vectors)]
    return {"object": "list", "data": data, "model": body.get("model", embed.MODEL),
            "usage": {"prompt_tokens": 0, "total_tokens": 0}}


class Embedder(wire.Server):
    def __init__(self, addr):
        super().__init__(addr, wire.Handler)

    def handle(self, path, body, headers):
        if path != wire.PATHS[1]:
            return 404, f"only {wire.PATHS[1]}"
        return 200, response(body)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8092)
    wire.serve(Embedder, ap.parse_args().port).serve_forever()


if __name__ == "__main__":
    main()
