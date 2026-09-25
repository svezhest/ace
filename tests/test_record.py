"""Запись и воспроизведение (tools/record) на фейковом апстриме."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np
import openai
import pytest

from tools.record import wire
from tools.record.embeddings import Embedder
from tools.record.record import Recorder
from tools.record.replay import Replayer


class Fake(BaseHTTPRequestHandler):
    """Апстрим: отвечает номером вызова и сидом, запоминает, что ему пришло."""
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        srv = self.server
        srv.got.append((self.path, body))
        if self.path == "/v1/embeddings":
            inp = body["input"] if isinstance(body["input"], list) else [body["input"]]
            out = {"object": "list", "model": body["model"], "usage": {"prompt_tokens": 1, "total_tokens": 1},
                   "data": [{"object": "embedding", "index": i, "embedding": [len(s), 0.5]} for i, s in enumerate(inp)]}
        elif body["messages"][-1]["content"] == "fail":
            return self.send(500, {"error": {"message": "boom", "type": "server"}})
        else:
            text = f"call {len(srv.got)} seed {body.get('seed')}"
            out = {"id": f"x{len(srv.got)}", "object": "chat.completion", "created": 1, "model": body["model"],
                   "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
                   "usage": {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7}}
            if body.get("stream"):
                return self.frames(out, body)
        self.send(200, out)

    def frames(self, out, body):
        """stream: текст двумя кадрами, конец, usage (если просили), как у шлюза."""
        text, base = out["choices"][0]["message"]["content"], {k: out[k] for k in ("id", "created", "model")}
        base["object"] = "chat.completion.chunk"
        parts = [{"role": "assistant", "content": text[:4]}, {"content": text[4:]}]
        frames = [dict(base, choices=[{"index": 0, "delta": d, "finish_reason": None}]) for d in parts]
        frames.append(dict(base, choices=[{"index": 0, "delta": {}, "finish_reason": "stop"}]))
        if (body.get("stream_options") or {}).get("include_usage"):
            frames.append(dict(base, choices=[], usage=out["usage"]))
        data = b"".join(b"data: " + json.dumps(f).encode() + b"\n\n" for f in frames) + b"data: [DONE]\n\n"
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send(self, status, out):
        data = json.dumps(out).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def start(srv):
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


@pytest.fixture
def fake():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
    srv.got = []
    start(srv)
    yield srv
    srv.shutdown()


def client(srv):
    return openai.OpenAI(base_url=f"http://127.0.0.1:{srv.server_address[1]}/v1", api_key="k", max_retries=0)


def record(fake, tmp_path, seed=False):
    rec = start(Recorder(("127.0.0.1", 0), tmp_path / "rec.jsonl", f"http://127.0.0.1:{fake.server_address[1]}",
                         None, seed))
    return rec, client(rec)


def chat(c, text="hi", **kw):
    r = c.chat.completions.create(model="m", messages=[{"role": "user", "content": text}], **kw)
    return r.choices[0].message.content


def stream(c, text="hi", **kw):
    parts = c.chat.completions.create(model="m", messages=[{"role": "user", "content": text}], stream=True, **kw)
    return "".join(p.choices[0].delta.content or "" for p in parts if p.choices)


def lines(path):
    return [json.loads(x) for x in path.read_text().splitlines()]


def test_canon_normalizes_only_drop():
    a = wire.canon({"stream": True, "id": "r1", "model": "m", "temperature": 0.7, "messages": []})
    b = wire.canon({"messages": [], "temperature": 0.7, "model": "m"})
    assert a == b == '{"messages":[],"model":"m","temperature":0.7}'
    assert wire.canon({"temperature": 1}) != wire.canon({"temperature": 1.0})
    assert wire.canon({"messages": [{"b": 1, "a": 2}]}) == '{"messages":[{"a":2,"b":1}]}'


def test_record_pairs_and_repeats(fake, tmp_path):
    rec, c = record(fake, tmp_path)
    assert chat(c) == "call 1 seed None"
    assert stream(c) == "call 2 seed None"        # тот же запрос, stream не важен -> повтор 1
    assert chat(c, "other") == "call 3 seed None"
    rec.shutdown()
    r = lines(tmp_path / "rec.jsonl")
    assert [x["n"] for x in r] == [0, 1, 0]
    assert r[0]["request"] == r[1]["request"] == '{"messages":[{"content":"hi","role":"user"}],"model":"m"}'
    assert ["stream" in body for _, body in fake.got] == [False, True, False]     # stream клиента — stream наверх
    assert r[1]["response"]["choices"][0]["message"] == {"role": "assistant", "content": "call 2 seed None"}
    assert r[1]["response"]["usage"]["total_tokens"] == 7                        # usage наверху просит прокси
    assert r[2]["response"]["choices"][0]["message"]["content"] == "call 3 seed None"


def test_record_seed(fake, tmp_path):
    rec, c = record(fake, tmp_path, seed=True)
    chat(c)
    chat(c)
    chat(c, seed=5)
    rec.shutdown()
    c0 = wire.canon({"model": "m", "messages": [{"role": "user", "content": "hi"}]})
    seeds = [body.get("seed") for _, body in fake.got]
    assert seeds == [wire.seed_for(c0, 0), wire.seed_for(c0, 1), 5]
    assert seeds[0] != seeds[1]
    assert [x["seed"] for x in lines(tmp_path / "rec.jsonl")] == seeds[:2] + [None]


def test_record_appends_counts(fake, tmp_path):
    rec, c = record(fake, tmp_path)
    chat(c)
    rec.shutdown()
    rec, c = record(fake, tmp_path)
    chat(c)
    rec.shutdown()
    assert [x["n"] for x in lines(tmp_path / "rec.jsonl")] == [0, 1]


def test_replay_by_repeat_number(fake, tmp_path):
    rec, c = record(fake, tmp_path)
    want = [chat(c), chat(c), chat(c, "other"), stream(c, "s", stream_options={"include_usage": True})]
    emb = c.embeddings.create(model="e", input=["ab", "abc"]).data
    rec.shutdown()
    rep = start(Replayer(("127.0.0.1", 0), tmp_path / "rec.jsonl"))
    c = client(rep)
    # порядок разных запросов не важен, важен номер повтора одинаковых
    assert chat(c, "other") == want[2]
    assert stream(c) == want[0]
    assert chat(c) == want[1]
    assert chat(c, "s") == want[3]
    assert [e.embedding for e in c.embeddings.create(model="e", input=["ab", "abc"]).data] == [e.embedding for e in emb]
    assert rep.status() == {"recorded": 5, "served": 5, "misses": 0, "unused": 0}
    with pytest.raises(openai.BadRequestError, match="repeat n=2 was not recorded"):
        chat(c)
    rep.shutdown()


def test_replay_mismatch_diff(fake, tmp_path):
    rec, c = record(fake, tmp_path)
    c.chat.completions.create(model="m", temperature=0.7, messages=[
        {"role": "system", "content": "rules:\n- one\n- two"}, {"role": "user", "content": "q"}])
    rec.shutdown()
    rep = start(Replayer(("127.0.0.1", 0), tmp_path / "rec.jsonl"))
    with pytest.raises(openai.BadRequestError) as e:
        client(rep).chat.completions.create(model="m", temperature=0.7, messages=[
            {"role": "system", "content": "rules:\n- one\n- 2"}, {"role": "user", "content": "q"}])
    msg = e.value.body["message"]
    assert "not recorded" in msg
    assert "-    - two" in msg and "+    - 2" in msg
    assert rep.status()["misses"] == 1
    rep.shutdown()


def test_upstream_error_recorded_and_replayed(fake, tmp_path):
    rec, c = record(fake, tmp_path)
    with pytest.raises(openai.InternalServerError):
        chat(c, "fail")
    rec.shutdown()
    assert lines(tmp_path / "rec.jsonl")[0]["status"] == 500
    rep = start(Replayer(("127.0.0.1", 0), tmp_path / "rec.jsonl"))
    with pytest.raises(openai.InternalServerError, match="boom"):
        chat(client(rep), "fail")
    rep.shutdown()


def test_sse_tool_calls_and_usage():
    resp = {"id": "a", "created": 1, "model": "m", "usage": {"total_tokens": 2},
            "choices": [{"index": 0, "finish_reason": "tool_calls", "message": {
                "role": "assistant", "content": None,
                "tool_calls": [{"id": "t", "type": "function", "function": {"name": "f", "arguments": "{}"}}]}}]}
    frames = [x[6:] for x in wire.sse(resp, {"stream_options": {"include_usage": True}}).decode().split("\n\n") if x]
    assert frames[-1] == "[DONE]"
    first, last, usage = (json.loads(f) for f in frames[:-1])
    assert first["choices"][0]["delta"]["tool_calls"][0]["index"] == 0
    assert "content" not in first["choices"][0]["delta"]
    assert last["choices"][0]["finish_reason"] == "tool_calls"
    assert usage["usage"] == {"total_tokens": 2}


def test_embeddings_server(monkeypatch):
    """Сервер эмбеддингов: клиент openai по умолчанию просит base64 и получает те же float32, что списком."""
    monkeypatch.setattr("ace.embed.embed", lambda texts: np.array([[len(t), 0.1] for t in texts], dtype="float32"))
    srv = start(Embedder(("127.0.0.1", 0)))
    c = client(srv)
    got = [d.embedding for d in c.embeddings.create(model="text-embedding-3-small", input=["ab", "c"]).data]
    listed = c.embeddings.create(model="text-embedding-3-small", input="ab", encoding_format="float").data[0].embedding
    srv.shutdown()
    assert got == [[2.0, np.float32(0.1).item()], [1.0, np.float32(0.1).item()]] and listed == got[0]


def test_record_cache(fake, tmp_path):
    """--cache: запрос, совпавший с прошлой записью после normalize, получает её ответ без апстрима."""
    rec, c = record(fake, tmp_path)
    chat(c, "a 1")
    chat(c, "a 1")
    rec.shutdown()
    first = tmp_path / "rec.jsonl"
    again = start(Recorder(("127.0.0.1", 0), tmp_path / "again.jsonl", f"http://127.0.0.1:{fake.server_address[1]}",
                           None, False, first, lambda s: s.replace("2", "1")))
    c = client(again)
    assert [chat(c, "a 2"), chat(c, "a 2"), chat(c, "a 2")] == ["call 1 seed None", "call 2 seed None", "call 3 seed None"]
    again.shutdown()
    r = lines(tmp_path / "again.jsonl")
    assert [x.get("cached", False) for x in r] == [True, True, False] and len(fake.got) == 3
    assert json.loads(r[0]["request"])["messages"][0]["content"] == "a 2" and [x["n"] for x in r] == [0, 1, 2]


def test_assemble_tool_calls():
    frames = [{"id": "i", "created": 1, "model": "m", "choices": [{"index": 0, "delta": {"role": "assistant", "tool_calls": [
                  {"index": 0, "id": "c1", "type": "function", "function": {"name": "w", "arguments": '{"a"'}}]}}]},
              {"choices": [{"index": 0, "delta": {"tool_calls": [{"index": 0, "function": {"arguments": ": 1}"}}]},
                            "finish_reason": "tool_calls"}]}]
    out = wire.assemble(frames)
    assert out["choices"][0]["message"] == {"role": "assistant", "content": None, "tool_calls": [
        {"function": {"arguments": '{"a": 1}', "name": "w"}, "id": "c1", "type": "function", "index": 0}]}
    assert out["choices"][0]["finish_reason"] == "tool_calls" and out["object"] == "chat.completion"
