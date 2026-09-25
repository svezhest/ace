"""Замер EvoLib: вердикт голосованием (evolib), судьёй (evolib_judge) и верным ответом (evolib_golden).
По каждому вопросу пишет ответы попыток, голос группы, баллы и IG, чтобы видеть, что без метки
IG = мера разногласия попыток (все совпали — 0; 2 из 3 — log(1/(2/3)) ≈ 0.41; все разные — log(1/(1/3)) ≈ 1.10),
а не мера правильности.
python scripts/evolib_ig.py TASK [N] [VARIANT ...]; итоги в results/TASKN/ig_VARIANT/ (ig.json рядом с логом)."""
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ablate import CHAIN  # noqa: E402
from ace import config  # noqa: E402
from ace.extract import IG, Extractor  # noqa: E402
from ace.learner import swap  # noqa: E402
from ace.loop import run  # noqa: E402
from ace.model import Model  # noqa: E402
from ace.tasks import TASKS  # noqa: E402

VARIANTS = ("evolib", "evolib_judge", "evolib_golden")
ROWS = []                   # общий на все копии ученика: run() копирует его вместе с извлечением


class Logged(Extractor):
    """Извлечение как было, плюс строка замера на вопрос."""
    def __init__(self, inner, variant):
        self.inner, self.variant, self.gives = inner, variant, inner.gives

    def __call__(self, ex, group, memory):
        x = self.inner(ex, group, memory)
        target = ex.item["target"]
        answers = [e.answer for e in group.episodes]
        ROWS.append(dict(variant=self.variant, epoch=ex.epoch, i=ex.i, target=target, answers=answers,
                         right=[ex.task.check(a, target) for a in answers], ok=[e.ok for e in group.episodes],
                         vote=group.vote, vote_right=ex.task.check(group.vote, target) if group.vote else None,
                         distinct=len(set(answers)), scores=x.scores if x else None,
                         ig=x.extras[IG] if x else None))
        return x


def mean(xs):
    return f"{sum(xs) / len(xs):.2f}" if xs else "-"


def table(rows):
    """IG по числу разных ответов в группе и по числу верных попыток."""
    print(f"{'variant':15} {'by':9} {'value':>5} {'n':>3} {'IG':>5}")
    for variant in dict.fromkeys(r["variant"] for r in rows):
        mine = [r for r in rows if r["variant"] == variant and r["ig"] is not None]
        for by, key in (("distinct", lambda r: r["distinct"]), ("right", lambda r: sum(r["right"]))):
            groups = defaultdict(list)
            for r in mine:
                groups[key(r)].append(r["ig"])
            for value in sorted(groups):
                print(f"{variant:15} {by:9} {value:>5} {len(groups[value]):>3} {mean(groups[value]):>5}")


if __name__ == "__main__":
    task = TASKS[sys.argv[1]]
    n = int(sys.argv[2]) if len(sys.argv) > 2 else config.SIZE
    for variant in sys.argv[3:] or VARIANTS:
        learner = CHAIN[variant]
        out = f"{config.RESULTS}/{task.name}{n}/ig_{variant}"
        start = len(ROWS)
        print(run(task, swap(learner, "ig_" + variant, extract=Logged(learner.extract, variant)), Model(), n, out,
                  epochs=config.EPOCHS))
        json.dump(ROWS[start:], open(f"{out}/ig.json", "w"), ensure_ascii=False, indent=1)
    table(ROWS)
