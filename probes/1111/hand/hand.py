"""Клиент почтового ящика run_hand.py: ход агента в сессии писателя.

  python3 probes/1111/hand/hand.py HOME TAG read          — что сейчас ждёт ответа (в начале: system, tools, первое сообщение)
  python3 probes/1111/hand/hand.py HOME TAG call <<'EOF'  — один ход: {"say": "...", "tool": "bash", "arguments": {...}}
  ...JSON...
  EOF

call ждёт ответа харнесса и печатает его. Битый JSON или неизвестное поле — отказ без хода.
"""
import glob
import json
import os
import sys
import time

HOME, TAG, CMD = sys.argv[1], sys.argv[2], sys.argv[3]
BOX = f"{HOME}/hand/{TAG}"
WAIT = 100


def pending():
    """-> номер хода, который ждёт ответа агента, или None."""
    ns = sorted(int(os.path.basename(p).split(".")[1]) for p in glob.glob(f"{BOX}/out.*.json"))
    if ns and not os.path.exists(f"{BOX}/in.{ns[-1]}.json"):
        return ns[-1]
    return None


def show(n):
    o = json.load(open(f"{BOX}/out.{n}.json"))
    for m in o["messages"]:
        print(f"=== {m['role']} ===")
        print(m.get("content") or "")
    if o["tools"] is not None:
        print("=== tools offered from this turn on ===")
        print(json.dumps(o["tools"], ensure_ascii=False, indent=1))
    print(f"=== turn {n}: your call ===")


def wait_next(after):
    t0 = time.time()
    while time.time() - t0 < WAIT:
        n = pending()
        if n is not None and n > after:
            return show(n)
        if os.path.exists(f"{BOX}/end.json"):
            e = json.load(open(f"{BOX}/end.json"))
            for r in e["last_results"]:
                print(f"=== tool ({r['name']}) ===")
                print(r["shown"] or "")
            return print(f"=== the session has ended: {e['reason']} ===")
        time.sleep(0.3)
    print("=== the harness is still working on it; run `read` to get the answer ===")


if CMD == "read":
    n = pending()
    show(n) if n is not None else wait_next(-1)
elif CMD == "call":
    n = pending()
    if n is None:
        sys.exit("no turn is waiting for a call (run `read`)")
    try:
        t = json.loads(sys.stdin.read())
        assert isinstance(t, dict) and set(t) <= {"say", "tool", "arguments"}, "keys: say, tool, arguments"
        assert isinstance(t.get("tool"), str) and isinstance(t.get("arguments"), dict), "tool: string, arguments: object"
        assert isinstance(t.get("say", ""), str), "say: string"
    except (ValueError, AssertionError) as e:
        sys.exit(f"not sent, the call could not be read: {e}")
    with open(f"{BOX}/in.{n}.json.tmp", "w") as f:
        json.dump(t, f, ensure_ascii=False)
    os.rename(f"{BOX}/in.{n}.json.tmp", f"{BOX}/in.{n}.json")
    wait_next(n)
else:
    sys.exit("read | call")
