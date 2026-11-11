"""Сессия писателя на внешней модели (DeepSeek): харнесс писателя тот же, вместо стенда — API провайдера.

  DEEPSEEK_API_KEY=... python3 probes/1111/ds/run_ds.py on|off -- АРГУМЕНТЫ РЕДАКТОРА (--stand не нужен)

on|off — рассуждение модели (thinking enabled / disabled). Ключ берётся из окружения и никуда не пишется.
Лог сессии — как у писателя (HOME/logs/TAG.jsonl: каждый ход, рассуждение, вызовы, ответы инструментов);
сырые запросы и ответы API — HOME/raw/TAG.jsonl.
В режиме рассуждения провайдер требует возвращать reasoning_content прежних ходов; в учёт окна харнесса
(HARD_AT) эти токены не идут: у писателя на стенде рассуждение в контекст не возвращается.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
from nrhsi.editor import cli  # noqa: E402
from nrhsi.editor.cfg import F  # noqa: E402
from nrhsi.researcher import cfg as RC  # noqa: E402

URL = os.environ.get("DS_BASE_URL", "https://api.deepseek.com/v1") + "/chat/completions"
MODEL = os.environ.get("DS_MODEL", "deepseek-flash")
KEY = os.environ["DEEPSEEK_API_KEY"]
THINK = sys.argv[1] == "on"
MAX_GEN = 16384 if THINK else 4096
REASON = []          # reasoning_content по порядку ответов ассистента
RAW = None


def apply_stand(name, roles=("agent",)):
    RC.URL, RC.MODEL, RC.TEMP, RC.MAX_GEN = URL, MODEL, 0.6, MAX_GEN
    RC.THINKING, RC.THINK_BUDGET = THINK, None
    RC.STAND = {"name": f"{MODEL}-{'thinking' if THINK else 'plain'}", "provider": URL, "model": MODEL,
                "thinking": THINK, "temperature": 0.6, "max_tokens": MAX_GEN, "offline_check": True}
    return RC.STAND


def chat(messages, temp, seed, tools=None, tool_choice=None):
    msgs, k = [], 0
    for m in messages:
        m = dict(m)
        if m["role"] == "assistant":
            if THINK and k < len(REASON):
                m["reasoning_content"] = REASON[k] or ""
            k += 1
        msgs.append(m)
    body = {"model": MODEL, "messages": msgs, "temperature": temp, "max_tokens": MAX_GEN,
            "thinking": {"type": "enabled" if THINK else "disabled"}}
    if tools:
        body["tools"] = tools
    req = urllib.request.Request(URL, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "Authorization": "Bearer " + KEY})
    resp = err = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=600) as r:
                resp, err = json.load(r), None
            break
        except urllib.error.HTTPError as e:
            err = f"HTTP {e.code}: {e.read().decode(errors='replace')[:500]}"
            if e.code < 500 and e.code != 429:
                break
        except Exception as e:  # noqa: BLE001
            err = f"{type(e).__name__}: {e}"
        time.sleep(5 * (attempt + 1))
    RAW.write(json.dumps({"t": time.strftime("%H:%M:%S"), "request": body, "response": resp, "error": err},
                         ensure_ascii=False) + "\n")
    RAW.flush()
    if err:
        return None, err
    try:
        msg = resp["choices"][0]["message"]
        rs = msg.get("reasoning_content") or ""
        REASON.append(rs)
        u = resp.get("usage") or {}
        echoed = sum(F.est_tokens(x) for x in REASON[:-1] if x) if THINK else 0
        u["prompt_tokens_raw"] = u.get("prompt_tokens") or 0
        u["prompt_tokens"] = max(0, (u.get("prompt_tokens") or 0) - echoed)
        resp["usage"] = u
    except Exception:  # noqa: BLE001
        REASON.append("")
    return resp, None


def main():
    global RAW
    cut = sys.argv.index("--")
    args = sys.argv[cut + 1:]
    home, tag = args[args.index("--home") + 1], args[args.index("--tag") + 1]
    os.makedirs(f"{home}/raw", exist_ok=True)
    RAW = open(f"{home}/raw/{tag}.jsonl", "w")
    F.apply_stand, F.chat = apply_stand, chat
    sys.argv = [sys.argv[0]] + args
    cli.main()


if __name__ == "__main__":
    main()
