"""EV36 (20.11): тот же пул и тот же вход, что EV35, но судит оценщик 9B T (профиль стенда) вместо Haiku.
  python3 probes/1120/ev36.py <профиль> [потоков]   → runs/evw_1113/ev36_<профиль>.jsonl (снятые теги пропускает)"""
import json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "1119"))
import ev35  # noqa: E402

STAND = sys.argv[1]
PROF = json.load(open(os.path.join(ev35.ROOT, "stands", STAND + ".json")))


def judge(system, user):
    """Ответ в форме ev35.one ({result, is_error}) плюс usage и рассуждение — для счёта упора."""
    try:
        r = ev35.EJ.call(PROF, system, user, 1)
    except Exception as e:  # noqa: BLE001 — сбой вызова пишется в запись, а не обрывает серию
        return {"is_error": True, "result": f"{type(e).__name__}: {e}"[:300]}
    m = r["choices"][0]["message"]
    return {"result": m.get("content") or "", "usage": r.get("usage"),
            "reasoning": m.get("reasoning_content") or m.get("reasoning")}


if __name__ == "__main__":
    ev35.haiku, ev35.OUT = judge, os.path.join(ev35.H, f"ev36_{STAND}.jsonl")
    ev35.main(int(sys.argv[2]) if len(sys.argv) > 2 else 4)
