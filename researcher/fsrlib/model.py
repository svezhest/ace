"""Вызов модели и разбор ответа API."""
import json
import urllib.error
import urllib.request

from . import cfg as C


# ---------------------------------------------------------------- модель

def chat(messages, temp, seed, tools=None, tool_choice=None):
    assert C.URL, "no stand profile applied (policy.apply_stand)"
    body = {"model": C.MODEL, "messages": messages, "temperature": temp, "seed": seed, "max_tokens": C.MAX_GEN}
    url = C.URL
    if C.THINKING:
        body["enable_thinking"] = True
        if C.THINK_BUDGET:
            body["thinking_budget"] = C.THINK_BUDGET
    if tools:
        body["tools"] = tools
    if tool_choice:
        body["tool_choice"] = tool_choice
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "Authorization": "Bearer x"})
    try:
        with urllib.request.urlopen(req, timeout=1800) as r:
            return json.load(r), None
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}: {e.read().decode(errors='replace')[:500]}"
    except Exception as e:  # noqa: BLE001
        return None, f"{type(e).__name__}: {e}"


def est_tokens(text):
    return int(len(text) / 3.0) + 8


API_RETRIES = 2          # v3c: повторы при битом ответе API ({}, пустые choices, нет message)
API_RETRY_SEC = 5


def _int(x):
    return x if isinstance(x, int) and not isinstance(x, bool) else 0


def parse_response(resp):
    """v3c: ответ API -> {content, calls, bad, finish_reason, usage} или (None, причина). calls приведены к виду
    {"id", "function": {"name", "arguments": str}}; вызовы без function.name отбрасываются и считаются в bad."""
    if not isinstance(resp, dict):
        return None, "the response is not a JSON object"
    chs = resp.get("choices")
    if not isinstance(chs, list) or not chs or not isinstance(chs[0], dict):
        return None, "no choices in the response"
    ch = chs[0]
    msg = ch.get("message")
    if not isinstance(msg, dict):
        return None, "no message in choices[0]"
    raw = msg.get("tool_calls") or []
    bad = 0
    if not isinstance(raw, list):
        raw, bad = [], 1
    calls = []
    for c in raw:
        f = c.get("function") if isinstance(c, dict) else None
        name = f.get("name") if isinstance(f, dict) else None
        if not isinstance(name, str) or not name:
            bad += 1
            continue
        a = f.get("arguments")
        a = "" if a is None else a if isinstance(a, str) else json.dumps(a, ensure_ascii=False)
        cid = c.get("id")
        calls.append({"id": cid if isinstance(cid, str) and cid else None, "function": {"name": name, "arguments": a}})
    content = msg.get("content")
    if content is not None and not isinstance(content, str):
        content = json.dumps(content, ensure_ascii=False)
    u = resp.get("usage")
    det = u.get("prompt_tokens_details") if isinstance(u, dict) else None
    u = {k: _int(v) for k, v in u.items() if not isinstance(v, dict)} if isinstance(u, dict) else {}
    if isinstance(det, dict) and "cached_tokens" in det:       # v3b: префикс-кэш воркера (шлюз: prompt_tokens_details)
        u["cached_tokens"] = _int(det["cached_tokens"])
    fr = ch.get("finish_reason")
    rs = msg.get("reasoning") or msg.get("reasoning_content")
    return {"reasoning": rs if isinstance(rs, str) else None,
            "content": content, "calls": calls, "bad": bad, "finish_reason": fr if isinstance(fr, str) else None,
            "usage": u}, None
