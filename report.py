"""Таблица по results/ (папка прогона — задача и размер / метод / протокол_модель_бэкенд): верно, отчётная точность
(acc: у finer — по сущностям, как у ACE), обрывы, вызовы модели, токены. Отметки у верных: * — зачёт pass@k (лучшая
попытка по метке), а не точность; ~ — прогон не закончен (итог пишется по ходу). Для каталога — доля вопросов с
чтением записей и точность с чтением и без; для хуков — сколько раз хук показан (fired) и сколько раз помог.
Считаются вопросы в зачёт (тест или последний проход); без log.json — только итог; err — вопросы, упавшие с ошибкой.
python report.py [results]"""
import json
import sys
from pathlib import Path

from ace.loop import in_score

HEADER = (f"{'run':64} {'ok':>6} {'acc':>5} {'trunc':>5} {'err':>4} {'calls':>6} {'tok':>9} {'read%':>6} "
          f"{'ok|read':>8} {'ok|none':>8} {'fired':>6} {'helped':>6}")


def final(log):
    """Записи, которые идут в зачёт: тест или последний онлайн-проход."""
    last = max((r.get("epoch", 0) for r in log), default=0)
    return [r for r in log if in_score(r, last)] or log


def acc(rows):
    return f"{sum(r['correct'] for r in rows) / len(rows):.2f}" if rows else "-"


def fired(log):
    """(показов хуков, из них помогли) по всем попыткам."""
    shows = [helped for r in log for e in r.get("group", []) for _, helped in e.get("fired", [])]
    return len(shows), sum(shows)


def row(root, path):
    """Строка таблицы по summary.json прогона; пропущенный прогон (итога нет) — None."""
    summary = json.load(path.open())
    if "correct" not in summary:
        return None
    log_path = path.parent / "log.json"
    log = final(json.load(log_path.open())) if log_path.exists() else []
    read = [r for r in log if r.get("read")]
    none = [r for r in log if not r.get("read")]
    share = f"{len(read) / len(log):.0%}" if read else "-"
    shows, helped = fired(log)
    if any(r.get("pass_at_k") for r in log):
        mark = "*"
    elif not summary.get("done", True):
        mark = "~"
    else:
        mark = " "
    if "accuracy" in summary:
        accuracy = summary["accuracy"]
    else:
        accuracy = summary["correct"] / max(summary["n"], 1)
    tokens = summary["prompt_tokens"] + summary["completion_tokens"]
    columns = [f"{str(path.parent.relative_to(root)):64}", f"{summary['correct']:>3}/{summary['n']:<2}{mark}",
               f"{accuracy:>5.2f}{summary['truncated']:>5}", f"{summary.get('errors', 0):>4}", f"{summary['calls']:>6}",
               f"{tokens:>9}", f"{share:>6}", f"{acc(read):>8}", f"{acc(none) if read else '-':>8}",
               f"{shows if shows else '-':>6}", f"{helped if shows else '-':>6}"]
    return " ".join(columns)


def main():
    root = Path(sys.argv[1] if len(sys.argv) > 1 else "results")
    print(HEADER)
    for path in sorted(root.rglob("summary.json")):
        line = row(root, path)
        if line is not None:
            print(line)
    print("* — pass@k: в зачёт лучшая попытка по метке")


if __name__ == "__main__":
    main()
