"""Профиль стенда — единственный источник модели и параметров генерации (stands/<имя>.json).

Каждый прогон и каждая сессия называют профиль явно, сверяют с ним живой стенд до старта и пишут профиль
(имя, хэш, содержимое) и итог сверки в мету. Другой режим (например, thinking) — другой профиль, закоммиченный
в git, а не флаг. Сверка только читает (lsof, ps) и шлёт один короткий запрос модели."""
import hashlib
import json
import os
import subprocess
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
DIR = os.path.join(ROOT, "stands")


def load(name):
    path = os.path.join(DIR, f"{name}.json")
    raw = open(path, "rb").read()
    prof = json.loads(raw)
    assert prof["name"] == name, f"{path}: name {prof['name']!r} != {name!r}"
    return {"name": name, "sha": hashlib.sha256(raw).hexdigest()[:16], "profile": prof}


def url(P, gateway):
    return f"http://127.0.0.1:{P['profile']['gateways'][gateway]['port']}/v1"


def gen(P, role, bench=None):
    """Параметры генерации роли: executor (с bench) или agent; плюс адрес и имя модели."""
    prof = P["profile"]
    r = prof[role]
    g = dict(r[bench]) if role == "executor" else {k: v for k, v in r.items() if k != "gateway"}
    g.update(url=url(P, r["gateway"]), model=prof["model"], thinking=g.get("thinking", False))
    return g


def _run(*cmd):
    return subprocess.run(cmd, capture_output=True, text=True).stdout


def _env(pid, prefix):
    return {k: v for k, _, v in (t.partition("=") for t in _run("ps", "eww", "-p", str(pid)).split())
            if k.startswith(prefix)}


def _probe(P, gw):
    """Один запрос: имя модели в ответе, соблюдён ли max_tokens, есть ли рассуждение там, где его не ждём."""
    spec = P["profile"]["gateways"][gw]
    body = {"model": P["profile"]["model"], "temperature": 0.0, "max_tokens": 6,
            "messages": [{"role": "user", "content": "Write the numbers from 1 to 40, separated by spaces."}]}
    if spec["thinking"]:
        body.update(max_tokens=80, enable_thinking=True, thinking_budget=16)
    req = urllib.request.Request(url(P, gw) + "/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "Authorization": "Bearer x"})
    with urllib.request.urlopen(req, timeout=300) as r:
        resp = json.load(r)
    ch, u = resp["choices"][0], resp.get("usage") or {}
    reasoning = ch["message"].get("reasoning") or ch["message"].get("reasoning_content") or ""
    errs = []
    if resp.get("model") != P["profile"]["served_model"]:
        errs.append(f"{gw}: the reply names model {resp.get('model')!r}, expected {P['profile']['served_model']!r}")
    if (u.get("completion_tokens") or 0) > body["max_tokens"]:
        errs.append(f"{gw}: max_tokens {body['max_tokens']} not kept ({u.get('completion_tokens')} tokens)")
    if bool(reasoning) != spec["thinking"]:
        errs.append(f"{gw}: reasoning {'present' if reasoning else 'absent'}, profile thinking={spec['thinking']}")
    return {"model": resp.get("model"), "finish_reason": ch.get("finish_reason"), "usage": u,
            "reasoning_chars": len(reasoning)}, errs


def check(P, roles):
    """Живой стенд против профиля для ролей roles (executor / agent). -> запись для меты; расхождение -> SystemExit."""
    prof, errs, rec = P["profile"], [], {"gateways": {}, "worker": {}}
    pids = _run("lsof", "-nP", f"-iTCP:{prof['worker']['port']}", "-sTCP:LISTEN", "-t").split()
    rec["worker"] = {p: _env(p, "QWEN_") for p in pids}
    if len(pids) != prof["worker"]["count"]:
        errs.append(f"worker: {len(pids)} listeners on :{prof['worker']['port']}, expected {prof['worker']['count']}")
    for p, env in rec["worker"].items():
        if env != prof["worker"]["env"]:
            diff = sorted(set(env.items()) ^ set(prof["worker"]["env"].items()))
            errs.append(f"worker {p}: QWEN_* env differs: {diff}")
    for gw in sorted({prof[r]["gateway"] for r in roles}):
        spec = prof["gateways"][gw]
        lp = _run("lsof", "-nP", f"-iTCP:{spec['port']}", "-sTCP:LISTEN", "-t").split()
        got = [{"pid": p, "cmd": _run("ps", "-o", "command=", "-p", p).strip(), "env": _env(p, "GATEWAY_")} for p in lp]
        rec["gateways"][gw] = got
        if len(got) != 1:
            errs.append(f"{gw}: {len(got)} listeners on :{spec['port']}, expected 1")
            continue
        if got[0]["cmd"] != spec["cmd"]:
            errs.append(f"{gw}: :{spec['port']} is served by {got[0]['cmd']!r}, expected {spec['cmd']!r}")
        if got[0]["env"] != spec["env"]:
            diff = sorted(set(got[0]["env"].items()) ^ set(spec["env"].items()))
            errs.append(f"{gw}: GATEWAY_* env differs: {diff}")
        if not errs:
            try:
                rec[f"probe_{gw}"], e = _probe(P, gw)
                errs += e
            except Exception as e:  # noqa: BLE001
                errs.append(f"{gw}: probe failed: {e!r}")
    if errs:
        raise SystemExit(f"stand does not match profile {P['name']!r} ({os.path.join(DIR, P['name'] + '.json')}):\n  - "
                         + "\n  - ".join(errs))
    return rec


def meta(P, rec):
    return {"name": P["name"], "sha": P["sha"], "profile": P["profile"], "check": rec}
