"""Проигрыш записанной сессии писателя без модели: ответы модели берутся из лога, инструменты исполняются настоящим
харнессом в свежей копии вида. Нужен, чтобы сверить механику до и после правки кода: два проигрыша одного лога
должны дать одинаковые логи, копии и diff (сравнение — editor/replay_cmp.py).

  python3 editor/replay.py LOG -- АРГУМЕНТЫ РЕДАКТОРА (--home и --tag — новые)

Промпт собирается нынешним кодом и с логом не сверяется: правки из лога могут не лечь на другой вид — это тоже
детерминированный ответ харнесса.
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from nrhsi.editor import cli, turn as TU  # noqa: E402


def main():
    cut = sys.argv.index("--")
    turns = iter([r for r in map(json.loads, open(sys.argv[1])) if r.get("type") == "turn" and not r.get("replayed")])

    def ask(run):
        st, r = run.st, next(turns, None)
        st["turns"] += 1
        st["final_turns"] += bool(run.final_left)
        if r is None or "error" in r:
            return None, 0.0, "forced: script end"
        return ({"calls": [{"id": None, "function": {"name": c["name"], "arguments": c["arguments"]}}
                           for c in r["tool_calls"]],
                 "content": r.get("content"), "reasoning": None, "usage": r.get("usage") or {},
                 "finish_reason": r.get("finish_reason"), "bad": False}, 0.0, None)

    TU.ask = ask
    sys.argv = ["editor"] + sys.argv[cut + 1:]
    cli.main()


if __name__ == "__main__":
    main()
