"""Сессия писателя, где за модель отвечает агент через почтовый ящик (шаг 4 тикета 10.11: эталонные сессии).
Харнесс писателя тот же: те же системный промпт и первое сообщение, песочница, инструменты, лимиты и проверки.

  python3 probes/1111/hand/run_hand.py -- АРГУМЕНТЫ РЕДАКТОРА (--stand не нужен)

Ящик — HOME/hand/TAG/: out.N.json (что харнесс добавил в разговор перед ходом N и какие инструменты предложены),
in.N.json (ход агента: текст и один вызов), end.json (конец сессии). Клиент — hand.py. Ящик свой у каждого TAG.
usage ответа — оценка по знакам (tokens = 145 + chars / 3.27, подгонка по 180 ходам записанных сессий 9B), чтобы
предел окна HARD_AT срабатывал там же, где у писателя. HAND_WAIT — сколько секунд ждать хода (по умолчанию 2400).
"""
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
from nrhsi.editor import cli  # noqa: E402
from nrhsi.editor.cfg import F  # noqa: E402
from nrhsi.researcher import cfg as RC  # noqa: E402

WAIT = int(os.environ.get("HAND_WAIT", "2400"))
BOX = None
S = {"n": 0, "sent": 0, "tools": None}


def put(name, obj):
    with open(f"{BOX}/{name}.tmp", "w") as f:
        json.dump(obj, f, ensure_ascii=False)
    os.rename(f"{BOX}/{name}.tmp", f"{BOX}/{name}")


def apply_stand(name, roles=("agent",)):
    RC.TEMP, RC.MAX_GEN, RC.THINKING, RC.THINK_BUDGET = 0.6, 4096, False, None      # числа базы; на агента не действуют
    RC.STAND = {"name": "hand", "model": os.environ.get("HAND_MODEL", "agent through the mailbox"), "offline_check": True}
    return RC.STAND


def chars(messages):
    return sum(len(m.get("content") or "") + sum(len(c["function"]["name"]) + len(c["function"]["arguments"])
                                                  for c in m.get("tool_calls") or []) for m in messages)


def chat(messages, temp, seed, tools=None, tool_choice=None):
    n = S["n"]
    names = [t["function"]["name"] for t in tools or []]
    put(f"out.{n}.json", {"n": n, "messages": [m for m in messages[S["sent"]:] if m["role"] != "assistant"],
                          "tools": tools if names != S["tools"] else None, "tool_names": names})
    S["sent"], S["tools"] = len(messages), names
    t0 = time.time()
    while not os.path.exists(f"{BOX}/in.{n}.json"):
        if time.time() - t0 > WAIT:
            return None, f"hand: no call in {WAIT} s"
        time.sleep(0.3)
    turn = json.load(open(f"{BOX}/in.{n}.json"))
    S["n"] += 1
    say, args = turn.get("say") or "", json.dumps(turn["arguments"], ensure_ascii=False)
    p, c = 145 + int(chars(messages) / 3.27), int((len(say) + len(args)) / 3.27) + 10
    return {"choices": [{"finish_reason": "tool_calls", "message": {
        "role": "assistant", "content": say,
        "tool_calls": [{"id": f"call_{n}", "type": "function", "function": {"name": turn["tool"], "arguments": args}}]}}],
        "usage": {"prompt_tokens": p, "completion_tokens": c, "total_tokens": p + c}}, None


def main():
    global BOX
    args = sys.argv[sys.argv.index("--") + 1:]
    home, tag = args[args.index("--home") + 1], args[args.index("--tag") + 1]
    BOX = f"{home}/hand/{tag}"
    os.makedirs(BOX, exist_ok=True)
    assert not os.listdir(BOX), f"{BOX} is not empty: one mailbox per session"
    F.apply_stand, F.chat = apply_stand, chat
    sys.argv = [sys.argv[0]] + args
    try:
        cli.main()
    finally:
        last, end = [], "forced: no end record"
        try:
            for line in open(f"{home}/logs/{tag}.jsonl"):
                r = json.loads(line)
                if r.get("type") == "turn":
                    last = [{"name": x.get("name"), "shown": x.get("shown")} for x in r.get("results") or []]
                if r.get("type") == "end":
                    end = r.get("reason")
        except OSError:
            pass
        put("end.json", {"reason": end, "last_results": last})


if __name__ == "__main__":
    main()
