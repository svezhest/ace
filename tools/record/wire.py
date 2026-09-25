"""Общее для записи и воспроизведения: канонический запрос, ключ, ответ клиенту (JSON или SSE)."""
import difflib
import hashlib
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# Единственное место, где решается, что в запросе не важно. Всё остальное сравнивается побайтно.
# stream_options бывает только вместе со stream.
DROP = ("stream", "stream_options", "id")

PATHS = ("/v1/chat/completions", "/v1/embeddings")


def canon(body: dict) -> str:
    """Канонический JSON: без полей DROP (верхний уровень), ключи по алфавиту, без пробелов."""
    body = {k: v for k, v in body.items() if k not in DROP}
    return json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def key(path: str, c: str) -> str:
    return path + " " + c


def seed_for(c: str, n: int) -> int:
    """Сид из канонического запроса и номера повтора: одинаковый запрос в n-й раз — тот же сид."""
    h = hashlib.sha256(f"{c}#{n}".encode()).digest()
    return int.from_bytes(h[:8], "big") >> 1


def wants_stream(body: dict) -> bool:
    return bool(body.get("stream"))


def sse(resp: dict, body: dict) -> bytes:
    """chat.completion -> кадры SSE, как их шлёт OpenAI: роль+текст, конец, usage (если просили)."""
    frames = []
    base = {k: resp.get(k) for k in ("id", "created", "model")}
    base["object"] = "chat.completion.chunk"
    for ch in resp.get("choices", []):
        msg = ch.get("message") or {}
        delta = {"role": msg.get("role", "assistant")}
        for k in ("content", "reasoning_content", "refusal"):
            if msg.get(k) is not None:
                delta[k] = msg[k]
        if msg.get("tool_calls"):
            delta["tool_calls"] = [dict(tc, index=i) for i, tc in enumerate(msg["tool_calls"])]
        idx = ch.get("index", 0)
        frames.append(dict(base, choices=[{"index": idx, "delta": delta, "finish_reason": None}]))
        frames.append(dict(base, choices=[{"index": idx, "delta": {}, "finish_reason": ch.get("finish_reason")}]))
    if (body.get("stream_options") or {}).get("include_usage") and "usage" in resp:
        frames.append(dict(base, choices=[], usage=resp["usage"]))
    out = b"".join(b"data: " + json.dumps(f, ensure_ascii=False).encode() + b"\n\n" for f in frames)
    return out + b"data: [DONE]\n\n"


def render(c: str) -> list[str]:
    """Канонический запрос построчно для diff: длинные строки (промпты) разворачиваются по \\n."""
    lines = []

    def walk(v, pre):
        if isinstance(v, dict):
            for k in v:
                walk(v[k], f"{pre}.{k}" if pre else k)
        elif isinstance(v, list):
            for i, x in enumerate(v):
                walk(x, f"{pre}[{i}]")
        elif isinstance(v, str) and "\n" in v:
            lines.append(f"{pre}:")
            lines.extend("    " + s for s in v.split("\n"))
        else:
            lines.append(f"{pre}: {json.dumps(v, ensure_ascii=False)}")

    walk(json.loads(c), "")
    return lines


def nearest(c: str, known: list[str]) -> str | None:
    """Ближайший записанный запрос: самый длинный общий префикс канонической строки."""
    def prefix(o):
        n = min(len(c), len(o))
        i = 0
        while i < n and c[i] == o[i]:
            i += 1
        return i
    return max(known, key=prefix, default=None)


def diff(got: str, want: str) -> str:
    return "\n".join(difflib.unified_diff(render(want), render(got), "recorded", "request", lineterm="", n=2))


class Handler(BaseHTTPRequestHandler):
    """Разбор запроса и ответ клиенту; что отвечать — решает handle(path, body) у наследника."""
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

    def reply(self, status: int, data: bytes, ctype="application/json"):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def error(self, status: int, msg: str, kind="replay_mismatch"):
        self.reply(status, json.dumps({"error": {"message": msg, "type": kind}}, ensure_ascii=False).encode())

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        path = self.path.split("?")[0]
        if path not in PATHS:
            return self.error(404, f"unsupported path {path}", "not_found")
        try:
            body = json.loads(raw)
        except ValueError as e:
            return self.error(400, f"bad json: {e}", "invalid_request")
        status, resp = self.server.handle(path, body, self.headers)
        if isinstance(resp, str):
            return self.error(status, resp, "upstream" if status == 502 else "replay_mismatch")
        if status == 200 and path == PATHS[0] and wants_stream(body):
            return self.reply(200, sse(resp, body), "text/event-stream")
        self.reply(status, json.dumps(resp, ensure_ascii=False).encode())


def serve(server_cls, port: int, *args):
    srv = server_cls(("127.0.0.1", port), *args)
    print(f"listening on http://127.0.0.1:{srv.server_address[1]}/v1", flush=True)
    return srv


class Server(ThreadingHTTPServer):
    daemon_threads = True
