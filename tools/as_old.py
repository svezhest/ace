"""Трасса новых методов с настройками старого кода там, где новый код сознательно решает иначе (DEVIATIONS.md):
так видно, что всё остальное совпадает с эталоном tools/ref_trace.json.
    uv run python tools/as_old.py OUT.json [method ...] && uv run python tools/compare.py OUT.json

    tfgrpo         в зачёт жадная попытка при T = 0, а не итоговый агент апстрима (T = 0.3, top_p 0.95);
                   опыты помечены id записей, а не местом G0, G1, ...
    evolib         ответ первой попытки подменён ответом большинства до вердикта группы (так делал старый
                   решатель с vote=True): её балл всегда 1, лучшая — всегда первая
    evolib_judge   то же; судья после всех попыток группы, а не после каждой"""
import importlib
import runpy
import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))
from ace import render, verdict  # noqa: E402
from ace.learner import swap  # noqa: E402
from ace.loop import Attempts, greedy  # noqa: E402
from ace.methods import METHODS  # noqa: E402

tfgrpo = importlib.import_module("ace.methods.tfgrpo")     # модуль: имя в пакете занято самим методом
evolib = importlib.import_module("ace.methods.evolib")


def old_tfgrpo():
    render.label = lambda i, r: r.id
    return swap(tfgrpo.tfgrpo, attempts=Attempts(1 + tfgrpo.GROUP, lambda k: 0 if k == 0 else tfgrpo.TEMPERATURE,
                                                 pick=greedy))


def first_is_vote(ex, group):
    group.episodes[0].answer = verdict.majority(e.answer for e in group.episodes)


def old_vote(ex, group):
    first_is_vote(ex, group)
    verdict.vote(ex, group)


def old_judge(ex, group):
    first_is_vote(ex, group)
    for e in group.episodes:
        verdict.judge(ex, e, "")


OLD = {"tfgrpo": old_tfgrpo,
       "evolib": lambda: swap(evolib.evolib, group_verdict=old_vote),
       "evolib_judge": lambda: swap(evolib.evolib_judge, verdict=verdict.none, group_verdict=old_judge)}

out, names = sys.argv[1], sys.argv[2:] or list(OLD)
for name in names:
    METHODS[name] = OLD[name]()
sys.argv = ["trace.py", out, *names]
runpy.run_path(str(root / "tools" / "trace.py"), run_name="__main__")
