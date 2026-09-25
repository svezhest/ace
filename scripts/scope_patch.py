"""Замер SCOPE: правило, принятое на шаге, переписывает системный промпт (scope_code, как в апстриме) или
дописывается сообщением в конец истории (scope_append). Оба с исполнением python: правило на шаге бывает
только у решателя с инструментами. Прогоны — ступени ablate.py; готовый прогон (summary.json есть) не
повторяется.
python scripts/scope_patch.py TASK [N]"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ablate import CHAIN  # noqa: E402
from ace import config  # noqa: E402
from ace.loop import run  # noqa: E402
from ace.model import Model  # noqa: E402
from ace.tasks import TASKS  # noqa: E402

VARIANTS = ("scope_code", "scope_append")


def acc(rows):
    return f"{sum(r['correct'] for r in rows) / len(rows):.2f} ({len(rows)})" if rows else "-"


if __name__ == "__main__":
    task = TASKS[sys.argv[1]]
    n = int(sys.argv[2]) if len(sys.argv) > 2 else config.SIZE
    print(f"{'variant':13} {'ok':>6} {'calls':>6} {'prompt_tok':>10} {'patched':>8} {'patches':>8} {'ok|patched':>11} {'ok|clean':>11}")
    for variant in VARIANTS:
        out = Path(f"{config.RESULTS}/{task.name}{n}/{variant}")
        if not (out / "summary.json").exists():
            run(task, CHAIN[variant], Model(), n, str(out), epochs=config.EPOCHS)
        summary, log = json.load((out / "summary.json").open()), json.load((out / "log.json").open())
        # попытка в зачёт: у scope она одна
        patched = [r for r in log if r["group"][0]["patches"]]
        clean = [r for r in log if not r["group"][0]["patches"]]
        patches = sum(len(r["group"][0]["patches"]) for r in log)
        print(f"{variant:13} {summary['correct']:>3}/{summary['n']:<2} {summary['calls']:>6} {summary['prompt_tokens']:>10}"
              f" {len(patched):>8} {patches:>8} {acc(patched):>11} {acc(clean):>11}")
