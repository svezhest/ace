"""Прокси записи и воспроизведение OpenAI-совместимого API (chat/completions, embeddings):
    uv run python -m tools.record.record OUT.jsonl [--port 8090] [--upstream URL] [--embeddings-upstream URL]
    uv run python -m tools.record.record REC.jsonl --replay [--port 8091]
Ключ ответа — (путь, канонический запрос, номер повтора этого запроса в прогоне). Канонический запрос — поля FIELDS
тела, ключи по алфавиту. Наверх уходит только он и seed = seed_for(запрос, n), так что ответ модели — функция
ключа и не зависит от порядка вызовов. Строка записи:
{"path", "request": канонический запрос, "n", "seed", "status", "response"}, плюс "dropped": true, если клиент
оборвал соединение до ответа (таймаут, повтор), и "error", если шлюз недоступен или его ответ не дочитан (клиенту
502) — такая запись негодна. Поле тела вне FIELDS и CLIENT — отказ 400: его нельзя молча потерять. Отказ и сбой
самого прокси — строка {"path", "request": тело как пришло, "status", "error"} без n.
Воспроизведение отдаёт k-му такому же запросу k-й записанный ответ; запроса нет в записи — 400 с diff против
ближайшего записанного. GET /_status — сколько отдано и сколько не востребовано."""
import argparse
import difflib
import hashlib
import json
import select
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, wait
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

CHAT = "/v1/chat/completions"
EMBEDDINGS = "/v1/embeddings"
# всё, что доходит до модели и входит в ключ
FIELDS = {
    CHAT: ("model", "messages", "tools", "tool_choice", "parallel_tool_calls", "response_format", "temperature",
           "top_p", "top_k", "min_p", "presence_penalty", "frequency_penalty", "max_tokens", "max_completion_tokens",
           "stop", "n", "logit_bias", "logprobs", "top_logprobs", "reasoning_effort", "enable_thinking",
           "thinking_budget"),
    EMBEDDINGS: ("model", "input", "dimensions", "encoding_format"),
}
# поля клиента, которые на ответ модели не влияют и отбрасываются: stream, stream_options — только раскладка ответа
# (прокси выбирает её сам); seed — прокси ставит свой seed_for; user — метка конечного пользователя для модерации
# у провайдера; metadata, store — хранение ответа у OpenAI; service_tier — тариф и очередь у OpenAI;
# prompt_cache_key — подсказка кэшу промптов у провайдера (ставит LiteLLM)
CLIENT = {
    CHAT: {"stream", "stream_options", "seed", "user", "metadata", "store", "service_tier", "prompt_cache_key"},
    EMBEDDINGS: {"user"},
}
UPSTREAM_TIMEOUT = 3600     # секунд на ответ модели
PING = 15                   # раз во столько секунд ожидания (замка или модели) клиенту уходят байты, чтобы не сработал
                            # его read-timeout


def canon(path: str, body: dict) -> str:
    return json.dumps({k: body[k] for k in FIELDS[path] if k in body}, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"))


def seed_for(c: str, n: int) -> int:
    h = hashlib.sha256(f"{c}#{n}".encode()).digest()
    return int.from_bytes(h[:8], "big") >> 1


def load(rec: Path) -> dict:
    """Запись -> {(путь, канонический запрос): [строки по номеру повтора]}. Ключ пересчитывается, поэтому читаются
    и записи старого прокси, у которого в запросе были и клиентские поля."""
    got = defaultdict(list)
    for line in rec.read_text().splitlines() if rec.exists() else []:
        r = json.loads(line)
        if "n" not in r:        # отказ прокси, запроса к модели не было
            continue
        got[r["path"], canon(r["path"], json.loads(r["request"]))].append(r)
    return got


class Recorder(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, addr, out: Path, upstream: str, emb_upstream: str | None = None, seed=True):
        assert seed, "seed подставляется всегда"      # аргумент оставлен для старых раннеров
        super().__init__(addr, Handler)
        self.out = out
        self.upstream = upstream.rstrip("/")
        self.emb_upstream = (emb_upstream or upstream).rstrip("/")
        self.count = Counter({k: len(v) for k, v in load(out).items()})
        self.lock = threading.Lock()
        self.write_lock = threading.Lock()

    def write(self, rec: dict):
        with self.write_lock, self.out.open("a") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def answer(self, path: str, body: dict, out: "Handler"):
        c = canon(path, body)
        # вызовы по одному: модель не видит соседних запросов, строки в файле идут в порядке вызовов
        out.wait(lambda t: self.lock.acquire(timeout=t), bool(body.get("stream")))
        try:
            n = self.count[path, c]
            sent = json.loads(c)
            seed = None
            if path == CHAT:
                seed = sent["seed"] = seed_for(c, n)
            stream = path == CHAT and bool(body.get("stream"))
            if stream:      # долгий ответ идёт кадрами сразу, иначе клиент бросает его по таймауту и шлёт заново
                sent.update(stream=True, stream_options={"include_usage": True})
            base = self.emb_upstream if path == EMBEDDINGS else self.upstream
            req = urllib.request.Request(base + path, json.dumps(sent).encode(), method="POST", headers={
                "Content-Type": "application/json", "Authorization": out.headers.get("Authorization") or "Bearer x"})
            with ThreadPoolExecutor(1) as pool:
                job = pool.submit(fetch, req, stream)
                out.wait(lambda t: wait([job], t).done, bool(body.get("stream")))
            error = None
            try:
                status, resp = job.result()
            except Exception as e:      # и сбой разбора ответа (assemble на странном кадре)
                unreachable = isinstance(e, urllib.error.URLError)
                error = f"upstream unreachable: {e}" if unreachable else f"upstream read failed: {e!r}"
                status, resp = 502, {"error": {"message": error, "type": "record"}}
            # клиент не дождался ответа (таймаут, повтор): апстрим его не увидел, запись негодна
            dropped = out.dropped or out.gone()
            try:
                if not dropped:
                    out.reply(status, resp, body)
            except OSError:
                dropped = True
            rec = {"path": path, "request": c, "n": n, "seed": seed, "status": status, "response": resp}
            if dropped:
                rec["dropped"] = True
            if error:
                rec["error"] = error
            self.write(rec)
            self.count[path, c] += 1
        finally:
            self.lock.release()

    def get(self, out: "Handler"):
        try:
            with urllib.request.urlopen(self.upstream + out.path, timeout=60) as r:
                out.send_raw(r.status, r.read())
        except urllib.error.HTTPError as e:
            out.send_raw(e.code, e.read())
        except urllib.error.URLError as e:
            out.error(502, f"upstream unreachable: {e}")


def fetch(req, stream: bool) -> tuple[int, dict]:
    """(код, ответ) шлюза; stream собирается в chat.completion. Таймаут или обрыв при чтении — исключение, как и
    stream с кадром error (так шлюз сообщает об ошибке после заголовков 200) или без [DONE]."""
    try:
        with urllib.request.urlopen(req, timeout=UPSTREAM_TIMEOUT) as up:
            if not stream:
                return up.status, json.loads(up.read())
            lines = [x.strip() for x in up]
            frames = [json.loads(x[6:]) for x in lines if x.startswith(b"data: ") and x != b"data: [DONE]"]
            errors = [f["error"] for f in frames if "error" in f]
            if errors or b"data: [DONE]" not in lines:
                raise ValueError(f"broken stream: {errors or 'no [DONE]'}")
            return up.status, assemble(frames)
    except urllib.error.HTTPError as e:
        return e.code, error_body(e)


class Replayer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, addr, rec: Path):
        super().__init__(addr, Handler)
        self.rec = load(rec)
        self.used = Counter()
        self.misses = 0
        self.lock = threading.Lock()

    def answer(self, path: str, body: dict, out: "Handler"):
        c = canon(path, body)
        with self.lock:
            got = self.rec.get((path, c), [])
            n = self.used[path, c]
            if n < len(got):
                self.used[path, c] += 1
                return out.reply(got[n]["status"], got[n]["response"], body)
            self.misses += 1
        msg = self.miss(path, c, n)
        print(msg, file=sys.stderr, flush=True)
        out.error(400, msg)

    def miss(self, path: str, c: str, n: int) -> str:
        if n:
            return f"{path}: request recorded {n} time(s), repeat n={n} was not recorded"
        known = [k for p, k in self.rec if p == path]
        if not known:
            return f"{path}: nothing recorded for this path"
        near = max(known, key=lambda k: common_prefix(c, k))
        return f"{path}: request not recorded; diff against nearest recorded:\n" + diff(c, near)

    def status(self) -> dict:
        total = sum(len(v) for v in self.rec.values())
        served = sum(self.used.values())
        return {"recorded": total, "served": served, "misses": self.misses, "unused": total - served}

    def get(self, out: "Handler"):
        if out.path == "/_status":
            return out.reply(200, self.status(), {})
        if out.path == "/v1/models":
            models = sorted({json.loads(c).get("model", "") for _, c in self.rec})
            return out.reply(200, {"object": "list", "data": [{"id": m, "object": "model"} for m in models]}, {})
        out.error(404, f"unsupported path {out.path}")


def common_prefix(a: str, b: str) -> int:
    return next((i for i, (x, y) in enumerate(zip(a, b)) if x != y), min(len(a), len(b)))


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


def diff(got: str, want: str) -> str:
    return "\n".join(difflib.unified_diff(render(want), render(got), "recorded", "request", lineterm="", n=2))


def error_body(error) -> dict:
    """Тело ответа с ошибкой: JSON как есть, иначе текст в оболочке ошибки OpenAI."""
    data = error.read()
    try:
        return json.loads(data)
    except ValueError:
        return {"error": {"message": data.decode(errors="replace"), "type": "upstream"}}


def sse(resp: dict, body: dict) -> bytes:
    """chat.completion -> кадры SSE, как их шлёт OpenAI: роль и текст, вызовы инструментов, конец, usage
    (если просили)."""
    frames = []
    base = {k: resp.get(k) for k in ("id", "created", "model")}
    base["object"] = "chat.completion.chunk"
    for ch in resp.get("choices", []):
        msg = ch.get("message") or {}
        delta = {"role": msg.get("role", "assistant")}
        for k in ("content", "reasoning_content", "reasoning", "refusal"):
            if msg.get(k) is not None:
                delta[k] = msg[k]
        deltas = [delta]
        # каждый вызов своими кадрами: из общего кадра LiteLLM передаёт дальше только первый вызов
        for i, tc in enumerate(msg.get("tool_calls") or []):
            fn = tc.get("function") or {}
            deltas.append({"tool_calls": [{"index": i, "id": tc.get("id"), "type": tc.get("type", "function"),
                                           "function": {"name": fn.get("name"), "arguments": ""}}]})
            deltas.append({"tool_calls": [{"index": i, "function": {"arguments": fn.get("arguments") or ""}}]})
        idx = ch.get("index", 0)
        frames += [dict(base, choices=[{"index": idx, "delta": d, "finish_reason": None}]) for d in deltas]
        frames.append(dict(base, choices=[{"index": idx, "delta": {}, "finish_reason": ch.get("finish_reason")}]))
    if (body.get("stream_options") or {}).get("include_usage") and "usage" in resp:
        frames.append(dict(base, choices=[], usage=resp["usage"]))
    out = b"".join(b"data: " + json.dumps(f, ensure_ascii=False).encode() + b"\n\n" for f in frames)
    return out + b"data: [DONE]\n\n"


def assemble(frames: list[dict]) -> dict:
    """Кадры chat.completion.chunk -> chat.completion, как его отдаёт сервер без stream."""
    choices = {}            # номер варианта -> сообщение, вызовы инструментов по номеру, finish_reason
    usage = None
    for f in frames:
        usage = f.get("usage") or usage
        for ch in f.get("choices") or []:
            got = choices.setdefault(ch.get("index", 0), [{"role": "assistant", "content": None}, {}, None])
            msg, calls = got[0], got[1]
            delta = ch.get("delta") or {}
            msg["role"] = delta.get("role") or msg["role"]
            for k in ("content", "reasoning_content", "reasoning", "refusal"):
                if delta.get(k) is not None:
                    msg[k] = (msg.get(k) or "") + delta[k]
            for tc in delta.get("tool_calls") or []:
                call = calls.setdefault(tc.get("index", 0), {"function": {"arguments": "", "name": ""}, "id": None,
                                                             "type": "function"})
                call["id"] = tc.get("id") or call["id"]
                call["type"] = tc.get("type") or call["type"]
                fn = tc.get("function") or {}
                call["function"]["name"] += fn.get("name") or ""
                call["function"]["arguments"] += fn.get("arguments") or ""
            got[2] = ch.get("finish_reason") or got[2]
    if not choices:
        choices[0] = [{"role": "assistant", "content": None}, {}, None]
    out = []
    for i, (msg, calls, finish) in sorted(choices.items()):
        if calls:
            msg["tool_calls"] = [dict(calls[j], index=j) for j in sorted(calls)]
        out.append({"finish_reason": finish, "index": i, "message": msg})
    first = frames[0] if frames else {}
    out = {"choices": out, "created": first.get("created"), "id": first.get("id"), "model": first.get("model"),
           "object": "chat.completion"}
    if usage:
        out["usage"] = usage
    return out


class Handler(BaseHTTPRequestHandler):
    """Разбор запроса и ответ клиенту; что отвечать, решает answer(path, body, self) у сервера."""
    protocol_version = "HTTP/1.1"
    started = False         # заголовки ответа уже ушли (ping)
    dropped = False         # ping не ушёл: клиент бросил запрос

    def log_message(self, fmt, *args):
        pass

    def send_raw(self, status: int, data: bytes, ctype="application/json"):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def reply(self, status: int, resp: dict, body: dict):
        """Ответ клиенту: кадрами, если он просил stream, иначе JSON. После ping заголовки 200 уже ушли: ответ
        дописывается в начатое тело, ошибка в stream — кадром error (клиент openai бросает APIError)."""
        data = json.dumps(resp, ensure_ascii=False).encode()
        if not self.started and status == 200 and body.get("stream"):
            return self.send_raw(200, sse(resp, body), "text/event-stream")
        if not self.started:
            return self.send_raw(status, data)
        if body.get("stream"):
            data = sse(resp, body) if status == 200 else b"data: " + data + b"\n\n"
        self.send(data)
        self.send(b"")

    def error(self, status: int, msg: str):
        if self.started:        # заголовки 200 ушли с ping: рвём тело, клиент увидит обрыв, а не успех
            self.close_connection = True
            return
        self.send_raw(status, json.dumps({"error": {"message": msg, "type": "record"}}, ensure_ascii=False).encode())

    def refuse(self, path: str, raw: bytes, status: int, msg: str):
        """Отказ без вызова модели: клиенту status, в запись (если это Recorder) строка с error."""
        if isinstance(self.server, Recorder):
            self.server.write({"path": path, "request": raw.decode(errors="replace"), "status": status, "error": msg})
        self.error(status, msg)

    def ping(self, stream: bool):
        """Байты, пока ждём модель: SSE-комментарий в stream, пробел перед JSON иначе (JSON его допускает)."""
        if not self.started:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream" if stream else "application/json")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            self.started = True
        self.send(b": ping\n\n" if stream else b" ")

    def wait(self, done, stream: bool):
        """Ждёт done(таймаут), раз в PING секунд шлёт клиенту ping; ping не ушёл — клиент бросил запрос."""
        while not done(max(0.0, self.last + PING - time.monotonic())):
            self.last = time.monotonic()
            try:
                if not self.dropped:
                    self.ping(stream)
            except OSError:
                self.dropped = True

    def send(self, data: bytes):
        """Кусок chunked-тела; пустой — конец."""
        self.wfile.write(b"%x\r\n%s\r\n" % (len(data), data))
        self.wfile.flush()

    def gone(self) -> bool:
        """Клиент закрыл соединение: тело запроса уже прочитано, так что читаемый сокет без данных — это конец."""
        try:
            ready = select.select([self.connection], [], [], 0)[0]
            return bool(ready) and not self.connection.recv(1, socket.MSG_PEEK)
        except OSError:
            return True

    def do_GET(self):
        self.started = False
        self.server.get(self)

    def do_POST(self):
        self.started = self.dropped = False
        self.last = time.monotonic()
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        path = self.path.split("?")[0]
        if path not in FIELDS:
            return self.error(404, f"unsupported path {path}")
        try:
            body = json.loads(raw)
        except ValueError as e:
            return self.refuse(path, raw, 400, f"bad json: {e}")
        try:
            unknown = sorted(set(body) - set(FIELDS[path]) - CLIENT[path])
            if unknown:
                msg = f"{path}: unknown request field(s) {', '.join(unknown)}: add to FIELDS or CLIENT in tools/record"
                print(msg, file=sys.stderr, flush=True)
                return self.refuse(path, raw, 400, msg)
            self.server.answer(path, body, self)
        except Exception as e:      # сбой прокси: клиенту 502, в записи строка с error
            msg = f"record failed: {e!r}"
            print(msg, file=sys.stderr, flush=True)
            self.refuse(path, raw, 502, msg)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("rec", type=Path)
    ap.add_argument("--replay", action="store_true")
    ap.add_argument("--port", type=int)
    ap.add_argument("--upstream")
    ap.add_argument("--embeddings-upstream")
    ap.add_argument("--seed", action="store_true", help="не нужен: seed подставляется всегда")
    a = ap.parse_args()
    if a.replay:
        srv = Replayer(("127.0.0.1", a.port or 8091), a.rec)
    else:
        if a.upstream is None:
            from ace import config      # не при импорте: контейнеры записи монтируют только tools/
            a.upstream = config.OPENAI_BASE_URL.removesuffix("/v1")
        srv = Recorder(("127.0.0.1", a.port or 8090), a.rec, a.upstream, a.embeddings_upstream)
    print(f"listening on http://127.0.0.1:{srv.server_address[1]}/v1", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
