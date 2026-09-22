"""Таблица по results/: верно / обрывов / вызовов модели / токенов, доля задач с чтением записей и точность с ним и без.
python report.py [results]"""
import json
import sys
from pathlib import Path

root = Path(sys.argv[1] if len(sys.argv) > 1 else "results")
print(f"{'run':32} {'ok':>5} {'trunc':>5} {'calls':>6} {'tok':>8} {'read%':>6} {'ok|read':>8} {'ok|none':>8}")
for s in sorted(root.glob("*/*/summary.json")):
    summary, log = json.load(s.open()), json.load((s.parent / "log.json").open())
    last = max((r.get("epoch", 0) for r in log), default=0)
    log = [r for r in log if r.get("phase", "online") == "test" or r.get("phase", "online") == "online" and r.get("epoch", 0) == last] or log
    read = [r for r in log if r.get("read", r.get("used"))]
    none = [r for r in log if not r.get("read", r.get("used"))]
    acc = lambda rows: f"{sum(r['correct'] for r in rows) / len(rows):.2f}" if rows else "-"
    print(f"{s.parent.parent.name + '/' + s.parent.name:32} {summary['correct']:>3}/{summary['n']:<2}"
          f"{summary['truncated']:>5} {summary['calls']:>6} {summary['prompt_tokens'] + summary['completion_tokens']:>8}"
          f"{len(read) / len(log):>6.0%} {acc(read):>8} {acc(none):>8}")
