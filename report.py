"""Таблица по results/: верно / обрывов / вызовов модели / токенов, доля задач с чтением записей и точность с ним и без.
Без log.json (старые или прерванные прогоны) — только итог.
python report.py [results]"""
import json
import sys
from pathlib import Path

root = Path(sys.argv[1] if len(sys.argv) > 1 else "results")


def final(log):
    """Записи, которые идут в зачёт: тест или последний онлайн-проход."""
    last = max((r.get("epoch", 0) for r in log), default=0)
    return [r for r in log if r.get("phase", "online") == "test" or r.get("phase", "online") == "online" and r.get("epoch", 0) == last] or log


def acc(rows):
    return f"{sum(r['correct'] for r in rows) / len(rows):.2f}" if rows else "-"


print(f"{'run':32} {'ok':>5} {'trunc':>5} {'calls':>6} {'tok':>8} {'read%':>6} {'ok|read':>8} {'ok|none':>8}")
for s in sorted(root.glob("*/*/summary.json")):
    summary = json.load(s.open())
    path = s.parent / "log.json"
    log = final(json.load(path.open())) if path.exists() else []
    read = [r for r in log if r.get("read", r.get("used"))]
    none = [r for r in log if not r.get("read", r.get("used"))]
    share = f"{len(read) / len(log):>6.0%}" if log else f"{'-':>6}"
    print(f"{s.parent.parent.name + '/' + s.parent.name:32} {summary['correct']:>3}/{summary['n']:<2}"
          f"{summary['truncated']:>5} {summary['calls']:>6} {summary['prompt_tokens'] + summary['completion_tokens']:>8}"
          f"{share} {acc(read):>8} {acc(none):>8}")
