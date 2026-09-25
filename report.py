"""Таблица по results/: верно, отчётная точность (acc: у finer — по сущностям, как у ACE), обрывы, вызовы модели, токены; * у верных — зачёт pass@k (лучшая попытка по
метке), а не точность. Для каталога — доля вопросов с чтением записей и точность с чтением и без; для хуков —
сколько раз хук показан (fired) и сколько раз помог. Считаются вопросы в зачёт (тест или последний проход).
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


def fired(log):
    """(показов хуков, из них помогли) по всем попыткам."""
    shows = [ok for r in log for e in r.get("group", []) for _, ok in e.get("fired", [])]
    return len(shows), sum(shows)


print(f"{'run':36} {'ok':>6} {'acc':>5} {'trunc':>5} {'calls':>6} {'tok':>9} {'read%':>6} {'ok|read':>8} {'ok|none':>8} {'fired':>6} {'helped':>6}")
for s in sorted(root.glob("*/*/summary.json")):
    summary = json.load(s.open())
    if "correct" not in summary:        # пропущенный прогон
        continue
    path = s.parent / "log.json"
    log = final(json.load(path.open())) if path.exists() else []
    read = [r for r in log if r.get("read")]
    none = [r for r in log if not r.get("read")]
    share = f"{len(read) / len(log):.0%}" if read else "-"
    shows, helped = fired(log)
    mark = "*" if any(r.get("pass_at_k") for r in log) else " "
    print(f"{s.parent.parent.name + '/' + s.parent.name:36} {summary['correct']:>3}/{summary['n']:<2}{mark}"
          f" {summary['accuracy'] if 'accuracy' in summary else summary['correct'] / max(summary['n'], 1):>5.2f}{summary['truncated']:>5} {summary['calls']:>6} {summary['prompt_tokens'] + summary['completion_tokens']:>9}"
          f" {share:>6} {acc(read) if read else '-':>8} {acc(none) if read else '-':>8}"
          f" {shows if shows else '-':>6} {helped if shows else '-':>6}")
print("* — pass@k: в зачёт лучшая попытка по метке")
