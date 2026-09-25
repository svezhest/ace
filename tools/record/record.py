"""Записывающий прокси OpenAI-совместимого API (chat/completions, embeddings):
    uv run python -m tools.record.record OUT.jsonl [--port 8090] [--upstream http://localhost:8080]
        [--embeddings-upstream URL] [--seed] [--cache REC.jsonl --normalize mce]
Клиенту — base_url http://127.0.0.1:PORT/v1. Каждая пара пишется строкой JSONL:
{"path", "request": канонический JSON, "n": номер повтора такого же запроса, "seed", "status", "response"}.
--seed: если в запросе chat/completions нет seed, подставить seed_for(запрос, n).
Наверх всегда уходит запрос без stream; клиенту, просившему stream, ответ отдаётся кадрами SSE.
--cache: ответ прошлой записи на запрос, совпавший с её запросом после normalize (k-й такой же запрос — её k-й
ответ, как у replay), в модель не идёт, но пишется в новую запись как есть; остальное — как обычно. Так запись
переснимается без повторных вызовов модели (MCE: вывод Bash хоста меняется от прогона к прогону, DEVIATIONS MCE7)."""
import argparse
import json
import threading
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

from tools.record import wire


class Recorder(wire.Server):
    def __init__(self, addr, out: Path, upstream: str, emb_upstream: str | None, seed: bool, cache: Path = None,
                 normalize=None):
        super().__init__(addr, RecordHandler)
        self.normalize = normalize or (lambda c: c)
        self.cache, self.hits = defaultdict(list), Counter()
        for line in cache.read_text().splitlines() if cache else []:
            r = json.loads(line)
            self.cache[wire.key(r["path"], self.normalize(r["request"]))].append(r)
        self.out, self.upstream, self.emb_upstream = out, upstream.rstrip("/"), (emb_upstream or upstream).rstrip("/")
        self.seed = seed
        self.lock = threading.Lock()
        self.count = Counter()
        if out.exists():        # дописываем: повторы считаются с учётом уже записанного
            for line in out.read_text().splitlines():
                r = json.loads(line)
                self.count[wire.key(r["path"], r["request"])] += 1

    def forward(self, path: str, body: dict, auth: str) -> tuple[int, dict]:
        base = self.emb_upstream if path.endswith("embeddings") else self.upstream
        req = urllib.request.Request(base + path, json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json",
                                              "Authorization": auth})
        try:
            with urllib.request.urlopen(req, timeout=3600) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            data = e.read()
            try:
                return e.code, json.loads(data)
            except ValueError:
                return e.code, {"error": {"message": data.decode(errors="replace"), "type": "upstream"}}

    def handle(self, path: str, body: dict, headers):
        c = wire.canon(body)
        k = wire.key(path, c)
        # весь запрос под замком: номер повтора и порядок строк в файле совпадают с порядком вызовов
        with self.lock:
            n = self.count[k]
            ck = wire.key(path, self.normalize(c))
            if self.hits[ck] < len(self.cache[ck]):
                old = self.cache[ck][self.hits[ck]]
                self.hits[ck] += 1
                rec = {"path": path, "request": c, "n": n, "seed": old["seed"], "status": old["status"],
                       "response": old["response"], "cached": True}
                with self.out.open("a") as f:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                self.count[k] += 1
                return old["status"], old["response"]
            sent = {x: v for x, v in body.items() if x not in ("stream", "stream_options")}
            seed = None
            if self.seed and path == wire.PATHS[0] and "seed" not in body:
                seed = sent["seed"] = wire.seed_for(c, n)
            try:
                status, resp = self.forward(path, sent, headers.get("Authorization") or "Bearer none")
            except urllib.error.URLError as e:     # шлюз недоступен: не пишем, номер повтора не тратим
                return 502, f"upstream unreachable: {e}"
            rec = {"path": path, "request": c, "n": n, "seed": seed, "status": status, "response": resp}
            with self.out.open("a") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            self.count[k] += 1
        return status, resp


class RecordHandler(wire.Handler):
    def do_GET(self):
        try:
            with urllib.request.urlopen(self.server.upstream + self.path, timeout=60) as r:
                self.reply(r.status, r.read())
        except urllib.error.HTTPError as e:
            self.reply(e.code, e.read())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out", type=Path)
    ap.add_argument("--port", type=int, default=8090)
    ap.add_argument("--upstream", default="http://localhost:8080")
    ap.add_argument("--embeddings-upstream")
    ap.add_argument("--seed", action="store_true")
    ap.add_argument("--cache", type=Path)
    ap.add_argument("--normalize", choices=["mce"])
    a = ap.parse_args()
    normalize = None
    if a.normalize == "mce":
        from tools.record.mce import normalize
    wire.serve(Recorder, a.port, a.out, a.upstream, a.embeddings_upstream, a.seed, a.cache, normalize).serve_forever()


if __name__ == "__main__":
    main()
