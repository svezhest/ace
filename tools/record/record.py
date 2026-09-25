"""Записывающий прокси OpenAI-совместимого API (chat/completions, embeddings):
    uv run python -m tools.record.record OUT.jsonl [--port 8090] [--upstream http://localhost:8080]
        [--embeddings-upstream URL] [--seed] [--cache REC.jsonl --normalize mce]
Клиенту — base_url http://127.0.0.1:PORT/v1. Каждая пара пишется строкой JSONL:
{"path", "request": канонический JSON, "n": номер повтора такого же запроса, "seed", "status", "response"}.
--seed: если в запросе chat/completions нет seed, подставить seed_for(запрос, n) (--seed-salt S — другая серия).
Клиенту, просившему stream, заголовки ответа идут сразу, наверх — тоже stream; в запись — ответ, собранный из
кадров (wire.assemble), клиенту — он же кадрами wire.sse, как у воспроизведения. Остальное наверх — без stream.
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
                 normalize=None, salt=""):
        super().__init__(addr, RecordHandler)
        self.salt = salt
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

    def write(self, path, c, n, seed, status, resp, **more):
        rec = {"path": path, "request": c, "n": n, "seed": seed, "status": status, "response": resp, **more}
        with self.out.open("a") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        self.count[wire.key(path, c)] += 1

    def cached(self, path, c, n):
        """Ответ прошлой записи (--cache) на этот запрос; есть — он же пишется в новую запись."""
        ck = wire.key(path, self.normalize(c))
        if self.hits[ck] >= len(self.cache[ck]):
            return None
        old = self.cache[ck][self.hits[ck]]
        self.hits[ck] += 1
        self.write(path, c, n, old["seed"], old["status"], old["response"], cached=True)
        return old["status"], old["response"]

    def prepare(self, path, body, c, n):
        """Запрос наверх: без stream, с seed_for, если просили --seed. -> (запрос, seed)."""
        sent = {x: v for x, v in body.items() if x not in ("stream", "stream_options")}
        seed = None
        if self.seed and path == wire.PATHS[0] and "seed" not in body:
            seed = sent["seed"] = wire.seed_for(c, n, self.salt)
        return sent, seed

    def handle(self, path: str, body: dict, headers):
        c = wire.canon(body)
        k = wire.key(path, c)
        # весь запрос под замком: номер повтора и порядок строк в файле совпадают с порядком вызовов
        with self.lock:
            n = self.count[k]
            hit = self.cached(path, c, n)
            if hit:
                return hit
            sent, seed = self.prepare(path, body, c, n)
            try:
                status, resp = self.forward(path, sent, headers.get("Authorization") or "Bearer none")
            except urllib.error.URLError as e:     # шлюз недоступен: не пишем, номер повтора не тратим
                return 502, f"upstream unreachable: {e}"
            self.write(path, c, n, seed, status, resp)
        return status, resp

    def stream(self, path: str, body: dict, headers, out: wire.Handler):
        """Клиент просит stream: заголовки ответа — сразу (долгий ответ не упирается в таймаут клиента: CLI
        Claude через LiteLLM иначе бросает его и шлёт заново), наверх тоже stream; в запись — ответ, собранный из
        кадров, как без stream, клиенту — он же кадрами wire.sse, как их отдаст воспроизведение."""
        c = wire.canon(body)
        with self.lock:
            n = self.count[wire.key(path, c)]
            hit = self.cached(path, c, n)
            if hit:
                return out.reply(hit[0], wire.sse(hit[1], body) if hit[0] == 200 else json.dumps(hit[1]).encode(),
                                 "text/event-stream" if hit[0] == 200 else "application/json")
            sent, seed = self.prepare(path, body, c, n)
            sent.update(stream=True, stream_options={"include_usage": True})
            req = urllib.request.Request(self.upstream + path, json.dumps(sent).encode(), method="POST",
                                         headers={"Content-Type": "application/json",
                                                  "Authorization": headers.get("Authorization") or "Bearer none"})
            try:
                up = urllib.request.urlopen(req, timeout=3600)
            except urllib.error.HTTPError as e:
                data = e.read()
                try:
                    resp = json.loads(data)
                except ValueError:
                    resp = {"error": {"message": data.decode(errors="replace"), "type": "upstream"}}
                self.write(path, c, n, seed, e.code, resp)
                return out.reply(e.code, json.dumps(resp).encode())
            except urllib.error.URLError as e:
                return out.error(502, f"upstream unreachable: {e}", "upstream")
            out.start_stream()
            frames = []
            with up:
                for line in up:
                    line = line.strip()
                    if line.startswith(b"data: ") and line != b"data: [DONE]":
                        frames.append(json.loads(line[6:]))
            resp = wire.assemble(frames)
            out.send(wire.sse(resp, body))
            out.end_stream()
            self.write(path, c, n, seed, 200, resp)


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
    ap.add_argument("--seed-salt", default="")
    a = ap.parse_args()
    normalize = None
    if a.normalize == "mce":
        from tools.record.mce import normalize
    wire.serve(Recorder, a.port, a.out, a.upstream, a.embeddings_upstream, a.seed, a.cache, normalize, a.seed_salt).serve_forever()


if __name__ == "__main__":
    main()
