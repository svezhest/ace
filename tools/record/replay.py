"""Воспроизведение записи tools/record/record.py на том же интерфейсе:
    uv run python -m tools.record.replay REC.jsonl [--port 8091]
Ответ отдаётся только на запрос, канонический JSON которого побайтно совпал с записанным (wire.DROP —
единственная нормализация), и по номеру повтора: k-й такой же запрос получает k-й записанный ответ.
Несовпадение — 400 с diff против ближайшего записанного запроса (и то же в stderr).
GET /_status — сколько ответов отдано и сколько не востребовано."""
import argparse
import json
import sys
import threading
from collections import Counter, defaultdict
from pathlib import Path

from tools.record import wire


class Replayer(wire.Server):
    """normalize(канонический запрос) -> строка сравнения, и у записанных, и у пришедших; по умолчанию — как есть.
    Нужна только там, где запрос несёт окружение, которое не воспроизвести (MCE: дата и время файлов в выводе
    инструментов CLI Claude, DEVIATIONS MCE7)."""
    def __init__(self, addr, rec: Path, normalize=None):
        super().__init__(addr, ReplayHandler)
        self.normalize = normalize or (lambda c: c)
        self.rec = defaultdict(list)       # ключ -> ответы по номеру повтора
        for line in rec.read_text().splitlines():
            r = json.loads(line)
            got = self.rec[wire.key(r["path"], self.normalize(r["request"]))]
            assert r["n"] == len(got), f"запись {r['path']} n={r['n']} не по порядку"
            got.append((r["status"], r["response"]))
        self.used = Counter()
        self.misses = 0
        self.lock = threading.Lock()

    def handle(self, path: str, body: dict, headers):
        c = self.normalize(wire.canon(body))
        k = wire.key(path, c)
        with self.lock:
            got = self.rec.get(k)
            n = self.used[k]
            if got is None or n >= len(got):
                self.misses += 1
                msg = self.miss(path, c, n)
                print(msg, file=sys.stderr, flush=True)
                return 400, msg
            self.used[k] += 1
            return got[n]

    def miss(self, path: str, c: str, n: int) -> str:
        if wire.key(path, c) in self.rec:
            return f"{path}: request recorded {n} time(s), repeat n={n} was not recorded"
        known = [k.split(" ", 1)[1] for k in self.rec if k.split(" ", 1)[0] == path]
        near = wire.nearest(c, known)
        if near is None:
            return f"{path}: nothing recorded for this path"
        return f"{path}: request not recorded; diff against nearest recorded:\n" + wire.diff(c, near)

    def status(self) -> dict:
        total = sum(len(v) for v in self.rec.values())
        return {"recorded": total, "served": sum(self.used.values()), "misses": self.misses,
                "unused": total - sum(self.used.values())}


class ReplayHandler(wire.Handler):
    def do_GET(self):
        if self.path == "/_status":
            return self.reply(200, json.dumps(self.server.status()).encode())
        if self.path == "/v1/models":
            models = sorted({json.loads(k.split(" ", 1)[1]).get("model", "") for k in self.server.rec})
            data = [{"id": m, "object": "model", "owned_by": "replay"} for m in models]
            return self.reply(200, json.dumps({"object": "list", "data": data}).encode())
        self.error(404, f"unsupported path {self.path}", "not_found")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("rec", type=Path)
    ap.add_argument("--port", type=int, default=8091)
    a = ap.parse_args()
    wire.serve(Replayer, a.port, a.rec).serve_forever()


if __name__ == "__main__":
    main()
