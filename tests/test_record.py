"""Запись и воспроизведение (tools/record) на фейковой модели."""
import hashlib
import json
import random
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np
import openai
import pytest

from tools.record import record
from tools.record.embeddings import Embedder
from tools.record.record import CHAT, Recorder, Replayer, assemble, canon, seed_for, sse


class Fake(BaseHTTPRequestHandler):
    """Модель: ответ — функция всего, что пришло (без stream) и сида; без сида — случайный, как у живой."""
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.got.append(body)
        if self.path == "/v1/embeddings":
            inp = body["input"] if isinstance(body["input"], list) else [body["input"]]
            out = {"object": "list", "model": body["model"], "usage": {"prompt_tokens": 1, "total_tokens": 1},
                   "data": [{"object": "embedding", "index": i, "embedding": [len(s), 0.5]} for i, s in enumerate(inp)]}
            return self.send(200, out)
        if body["messages"][-1]["content"] == "fail":
            return self.send(500, {"error": {"message": "boom", "type": "server"}})
        if body["messages"][-1]["content"] == "slow":
            time.sleep(0.5)
        seen = {k: v for k, v in body.items() if k not in ("stream", "stream_options")}
        seen.setdefault("seed", random.random())
        text = hashlib.sha256(json.dumps(seen, sort_keys=True).encode()).hexdigest()[:12]
        out = {"id": "x", "object": "chat.completion", "created": 1, "model": body["model"],
               "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
               "usage": {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7}}
        if not body.get("stream"):
            return self.send(200, out)
        # stream: текст двумя кадрами, конец, usage, как у шлюза
        base = {"id": "x", "created": 1, "model": body["model"], "object": "chat.completion.chunk"}
        frames = [dict(base, choices=[{"index": 0, "delta": d, "finish_reason": None}])
                  for d in ({"role": "assistant", "content": text[:4]}, {"content": text[4:]})]
        frames += [dict(base, choices=[{"index": 0, "delta": {}, "finish_reason": "stop"}]),
                   dict(base, choices=[], usage=out["usage"])]
        data = b"".join(b"data: " + json.dumps(f).encode() + b"\n\n" for f in frames) + b"data: [DONE]\n\n"
        self.send(200, data, "text/event-stream")

    def send(self, status, out, ctype="application/json"):
        data = out if isinstance(out, bytes) else json.dumps(out).encode()
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if self.server.got[-1].get("messages", [{}])[-1].get("content") == "cut":    # обрыв посреди ответа
            data = data[:len(data) // 2]
            self.close_connection = True
        self.wfile.write(data)


def start(srv):
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


@pytest.fixture
def fake():
    srv = start(ThreadingHTTPServer(("127.0.0.1", 0), Fake))
    srv.got = []
    yield srv
    srv.shutdown()


def client(srv):
    return openai.OpenAI(base_url=f"http://127.0.0.1:{srv.server_address[1]}/v1", api_key="k", max_retries=0)


def recorder(fake, path):
    return start(Recorder(("127.0.0.1", 0), path, f"http://127.0.0.1:{fake.server_address[1]}"))


def replayer(path):
    return start(Replayer(("127.0.0.1", 0), path))


def lines(path):
    return [json.loads(x) for x in path.read_text().splitlines()]


def ask(c, q):
    """Запрос набора: чат (обычный или stream) или эмбеддинги."""
    kind, text = q
    if kind == "emb":
        return [d.embedding for d in c.embeddings.create(model="e", input=[text, text + "!"]).data]
    kw = dict(model="m", messages=[{"role": "user", "content": text}], temperature=0.7)
    if kind == "stream":
        parts = c.chat.completions.create(stream=True, stream_options={"include_usage": True}, **kw)
        return "".join(p.choices[0].delta.content or "" for p in parts if p.choices)
    return c.chat.completions.create(user="u", **kw).choices[0].message.content


QUERIES = [("chat", "a"), ("chat", "a"), ("stream", "a"), ("chat", "b"), ("stream", "c"), ("emb", "x"), ("emb", "x")]


def answers(c, order):
    """Ответы на QUERIES в порядке order -> по (запрос, номер повтора), как их видит ключ записи."""
    seen, out = {}, {}
    for q in order:
        k = ("text" if q[0] != "emb" else "emb", q[1])      # stream — тот же запрос
        seen[k] = seen.get(k, -1) + 1
        out[k, seen[k]] = ask(c, q)
    return out


def test_canon_keeps_only_model_fields():
    a = canon(CHAT, {"stream": True, "stream_options": {}, "user": "u", "seed": 3, "metadata": {}, "model": "m",
                     "temperature": 0.7, "messages": [{"role": "user", "content": "q"}]})
    b = canon(CHAT, {"messages": [{"content": "q", "role": "user"}], "temperature": 0.7, "model": "m"})
    assert a == b == '{"messages":[{"content":"q","role":"user"}],"model":"m","temperature":0.7}'
    assert canon(CHAT, {"temperature": 1}) != canon(CHAT, {"temperature": 1.0})
    assert canon(CHAT, {"max_tokens": 5}) != canon(CHAT, {"max_completion_tokens": 5})


def test_answers_do_not_depend_on_order(fake, tmp_path):
    """Два прогона одного набора в разном порядке — те же ответы; replay по записи — тоже, в третьем порядке."""
    order = QUERIES[:]
    rec = recorder(fake, tmp_path / "1.jsonl")
    first = answers(client(rec), order)
    rec.shutdown()
    random.Random(1).shuffle(order)
    rec = recorder(fake, tmp_path / "2.jsonl")
    second = answers(client(rec), order)
    rec.shutdown()
    assert first == second
    a = [first[("text", "a"), n] for n in range(3)]
    assert len(set(a)) == 3                     # повторы — разные сиды
    c = lines(tmp_path / "1.jsonl")[0]["request"]
    assert [b["seed"] for b in fake.got if "messages" in b][:3] == [seed_for(c, n) for n in range(3)]
    assert not any("user" in b for b in fake.got)       # наверх только канонический запрос
    random.Random(2).shuffle(order)
    rep = replayer(tmp_path / "1.jsonl")
    assert answers(client(rep), order) == first
    assert rep.status() == {"recorded": 7, "served": 7, "misses": 0, "unused": 0}
    with pytest.raises(openai.BadRequestError, match="repeat n=3 was not recorded"):
        ask(client(rep), ("chat", "a"))
    rep.shutdown()


def test_replay_miss_shows_nearest(fake, tmp_path):
    rec = recorder(fake, tmp_path / "rec.jsonl")
    msgs = [{"role": "system", "content": "rules:\n- one\n- two"}, {"role": "user", "content": "q"}]
    client(rec).chat.completions.create(model="m", messages=msgs)
    rec.shutdown()
    rep = replayer(tmp_path / "rec.jsonl")
    msgs[0]["content"] = "rules:\n- one\n- 2"
    with pytest.raises(openai.BadRequestError) as e:
        client(rep).chat.completions.create(model="m", messages=msgs)
    assert "not recorded" in e.value.body["message"]
    assert "-    - two" in e.value.body["message"] and "+    - 2" in e.value.body["message"]
    assert rep.status()["misses"] == 1
    rep.shutdown()


def test_old_record_with_client_fields(tmp_path):
    """Запись старого прокси: в запросе и клиентские поля; ключ пересчитывается."""
    req = json.dumps({"model": "m", "messages": [{"role": "user", "content": "q"}], "user": "u", "seed": 1})
    resp = {"choices": [{"index": 0, "message": {"role": "assistant", "content": "old"}, "finish_reason": "stop"}]}
    (tmp_path / "rec.jsonl").write_text(json.dumps({"path": CHAT, "request": req, "n": 0, "seed": 5, "status": 200,
                                                    "response": resp}) + "\n")
    rep = replayer(tmp_path / "rec.jsonl")
    got = client(rep).chat.completions.create(model="m", messages=[{"role": "user", "content": "q"}])
    assert got.choices[0].message.content == "old"
    rep.shutdown()


def test_upstream_error_recorded_and_replayed(fake, tmp_path):
    rec = recorder(fake, tmp_path / "rec.jsonl")
    with pytest.raises(openai.InternalServerError):
        ask(client(rec), ("chat", "fail"))
    rec.shutdown()
    assert lines(tmp_path / "rec.jsonl")[0]["status"] == 500
    rep = replayer(tmp_path / "rec.jsonl")
    with pytest.raises(openai.InternalServerError, match="boom"):
        ask(client(rep), ("chat", "fail"))
    rep.shutdown()


def test_record_appends_counts(fake, tmp_path):
    for _ in range(2):
        rec = recorder(fake, tmp_path / "rec.jsonl")
        ask(client(rec), ("chat", "a"))
        rec.shutdown()
    assert [x["n"] for x in lines(tmp_path / "rec.jsonl")] == [0, 1]


def test_sse_and_assemble_tool_calls():
    msg = {"role": "assistant", "content": None,
           "tool_calls": [{"id": "t", "type": "function", "function": {"name": "f", "arguments": "{}"}, "index": 0}]}
    resp = {"id": "a", "created": 1, "model": "m", "object": "chat.completion", "usage": {"total_tokens": 2},
            "choices": [{"index": 0, "finish_reason": "tool_calls", "message": msg}]}
    frames = [x[6:] for x in sse(resp, {"stream_options": {"include_usage": True}}).decode().split("\n\n") if x]
    assert frames[-1] == "[DONE]"
    assert assemble([json.loads(f) for f in frames[:-1]]) == resp


def test_sse_tool_calls_frame_by_frame():
    """Каждый вызов своими кадрами: сначала id и имя, потом аргументы; конец — отдельным кадром."""
    calls = [{"id": f"t{i}", "type": "function", "function": {"name": f"f{i}", "arguments": f'{{"a":{i}}}'},
              "index": i} for i in range(2)]
    resp = {"id": "a", "created": 1, "model": "m", "object": "chat.completion",
            "choices": [{"index": 0, "finish_reason": "tool_calls",
                         "message": {"role": "assistant", "content": None, "tool_calls": calls}}]}
    frames = [json.loads(x[6:]) for x in sse(resp, {}).decode().split("\n\n") if x and x != "data: [DONE]"]
    deltas = [f["choices"][0]["delta"].get("tool_calls") for f in frames]
    assert deltas[1:5] == [[{"index": 0, "id": "t0", "type": "function", "function": {"name": "f0", "arguments": ""}}],
                           [{"index": 0, "function": {"arguments": '{"a":0}'}}],
                           [{"index": 1, "id": "t1", "type": "function", "function": {"name": "f1", "arguments": ""}}],
                           [{"index": 1, "function": {"arguments": '{"a":1}'}}]]
    assert [f["choices"][0]["finish_reason"] for f in frames] == [None] * 5 + ["tool_calls"]
    assert assemble(frames) == resp


@pytest.mark.parametrize("stream", [False, True])
def test_client_drop_marked(fake, tmp_path, stream):
    """Клиент бросил запрос по таймауту — строка записи помечена dropped; дождавшийся — нет."""
    rec = recorder(fake, tmp_path / "rec.jsonl")
    c = openai.OpenAI(base_url=f"http://127.0.0.1:{rec.server_address[1]}/v1", api_key="k", max_retries=0, timeout=0.1)
    with pytest.raises(openai.APITimeoutError):
        list(c.chat.completions.create(model="m", messages=[{"role": "user", "content": "slow"}], stream=stream))
    ask(client(rec), ("stream" if stream else "chat", "a"))       # ждёт за брошенным: вызовы по одному
    rec.shutdown()
    assert [x.get("dropped") for x in lines(tmp_path / "rec.jsonl")] == [True, None]


def test_embeddings_server(monkeypatch):
    """Сервер эмбеддингов: клиент openai по умолчанию просит base64 и получает те же float32, что списком."""
    monkeypatch.setattr("tools.record.embeddings.embed", lambda texts: np.array([[len(t), 0.1] for t in texts], dtype="float32"))
    srv = start(Embedder(("127.0.0.1", 0)))
    c = client(srv)
    got = [d.embedding for d in c.embeddings.create(model="text-embedding-3-small", input=["ab", "c"]).data]
    listed = c.embeddings.create(model="text-embedding-3-small", input="ab", encoding_format="float").data[0].embedding
    srv.shutdown()
    assert got == [[2.0, np.float32(0.1).item()], [1.0, np.float32(0.1).item()]] and listed == got[0]


def test_unknown_field_rejected(fake, tmp_path, capsys):
    rec = recorder(fake, tmp_path / "rec.jsonl")
    with pytest.raises(openai.BadRequestError, match="chat_template_kwargs"):
        client(rec).chat.completions.create(model="m", messages=[{"role": "user", "content": "q"}],
                                            extra_body={"chat_template_kwargs": {"enable_thinking": False}})
    rec.shutdown()
    assert "unknown request field(s) chat_template_kwargs" in capsys.readouterr().err
    [line] = lines(tmp_path / "rec.jsonl")
    assert not fake.got and line["status"] == 400 and "chat_template_kwargs" in line["error"]


def test_sse_and_assemble_choices_reasoning_refusal():
    """n=2: варианты не сливаются; reasoning и refusal доходят до собранного ответа."""
    msgs = [{"role": "assistant", "content": "a", "reasoning": "r"}, {"role": "assistant", "content": None,
                                                                      "refusal": "no"}]
    resp = {"id": "a", "created": 1, "model": "m", "object": "chat.completion",
            "choices": [{"index": i, "finish_reason": "stop", "message": m} for i, m in enumerate(msgs)]}
    frames = [json.loads(x[6:]) for x in sse(resp, {}).decode().split("\n\n") if x and x != "data: [DONE]"]
    assert assemble(frames) == resp


def test_upstream_down(tmp_path):
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    rec = start(Recorder(("127.0.0.1", 0), tmp_path / "rec.jsonl", f"http://127.0.0.1:{port}"))
    with pytest.raises(openai.InternalServerError, match="upstream unreachable"):
        client(rec).models.list()
    with pytest.raises(openai.InternalServerError, match="upstream unreachable"):
        ask(client(rec), ("chat", "a"))
    rec.shutdown()
    [line] = lines(tmp_path / "rec.jsonl")
    assert line["status"] == 502 and "upstream unreachable" in line["error"]


@pytest.mark.parametrize("stream", [False, True])
def test_keepalive_outlasts_client_timeout(fake, tmp_path, monkeypatch, stream):
    """Модель отвечает дольше read-timeout клиента: пока ждём, клиенту уходят байты, и он дожидается ответа."""
    monkeypatch.setattr(record, "PING", 0.05)
    rec = recorder(fake, tmp_path / "rec.jsonl")
    c = openai.OpenAI(base_url=f"http://127.0.0.1:{rec.server_address[1]}/v1", api_key="k", max_retries=0, timeout=0.2)
    got = c.chat.completions.create(model="m", messages=[{"role": "user", "content": "slow"}], stream=stream)
    text = "".join(p.choices[0].delta.content or "" for p in got) if stream else got.choices[0].message.content
    rec.shutdown()
    [line] = lines(tmp_path / "rec.jsonl")
    assert text == line["response"]["choices"][0]["message"]["content"] and len(text) == 12
    assert "dropped" not in line and "error" not in line


@pytest.mark.parametrize("q", [("chat", "cut"), ("stream", "cut"), ("chat", "slow"), ("stream", "slow")])
def test_upstream_read_error_recorded(fake, tmp_path, monkeypatch, q):
    """Обрыв или таймаут при чтении ответа шлюза: клиенту 502, в записи строка с error; прокси работает дальше."""
    monkeypatch.setattr(record, "UPSTREAM_TIMEOUT", 0.2)
    rec = recorder(fake, tmp_path / "rec.jsonl")
    with pytest.raises(openai.InternalServerError, match="upstream read failed"):
        ask(client(rec), q)
    ask(client(rec), ("chat", "a"))
    rec.shutdown()
    bad, ok = lines(tmp_path / "rec.jsonl")
    assert bad["status"] == 502 and "upstream read failed" in bad["error"] and "error" not in ok


def test_read_error_after_ping_is_error_frame(fake, tmp_path, monkeypatch):
    """Заголовки 200 уже ушли с ping, потом таймаут шлюза: в stream клиент получает кадр error."""
    monkeypatch.setattr(record, "PING", 0.05)
    monkeypatch.setattr(record, "UPSTREAM_TIMEOUT", 0.3)
    rec = recorder(fake, tmp_path / "rec.jsonl")
    with pytest.raises(openai.APIError, match="upstream read failed"):
        ask(client(rec), ("stream", "slow"))
    rec.shutdown()
    assert lines(tmp_path / "rec.jsonl")[0]["status"] == 502


@pytest.mark.parametrize("stream", [False, True])
def test_keepalive_while_waiting_for_lock(fake, tmp_path, monkeypatch, stream):
    """Три клиента разом, модель 0,5 с, read-timeout 0,75 с: ping получают и ждущие замка, все дожидаются ответа."""
    monkeypatch.setattr(record, "PING", 0.05)
    rec = recorder(fake, tmp_path / "rec.jsonl")
    c = openai.OpenAI(base_url=f"http://127.0.0.1:{rec.server_address[1]}/v1", api_key="k", max_retries=0, timeout=0.75)

    def one(_):
        got = c.chat.completions.create(model="m", messages=[{"role": "user", "content": "slow"}], stream=stream)
        return "".join(p.choices[0].delta.content or "" for p in got) if stream else got.choices[0].message.content

    with ThreadPoolExecutor(3) as pool:
        texts = list(pool.map(one, range(3)))
    rec.shutdown()
    got = lines(tmp_path / "rec.jsonl")
    assert sorted(texts) == sorted(x["response"]["choices"][0]["message"]["content"] for x in got)
    assert len(set(texts)) == 3 and not any("dropped" in x or "error" in x for x in got)


@pytest.mark.parametrize("where", ["assemble", "canon"])
def test_proxy_failure_recorded(fake, tmp_path, monkeypatch, where):
    """Любое исключение в прокси (TypeError в assemble на странном кадре и т. п.): клиенту 502, в записи строка
    с error; прокси работает дальше."""
    def odd(*a):
        raise TypeError("odd")

    monkeypatch.setattr(record, where, odd)
    rec = recorder(fake, tmp_path / "rec.jsonl")
    with pytest.raises(openai.InternalServerError, match="odd"):
        ask(client(rec), ("stream", "a"))
    monkeypatch.undo()
    ask(client(rec), ("chat", "a"))
    rec.shutdown()
    bad, ok = lines(tmp_path / "rec.jsonl")
    assert bad["status"] == 502 and "TypeError('odd')" in bad["error"] and "error" not in ok
