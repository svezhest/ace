"""Трасса новых методов с настройками старого кода там, где новый код сознательно решает иначе (DEVIATIONS.md):
так видно, что всё остальное совпадает с эталоном tools/ref_trace.json.
    uv run python tools/as_old.py OUT.json [method ...] && uv run python tools/compare.py OUT.json

    tfgrpo         в зачёт жадная попытка при T = 0, а не итоговый агент апстрима (T = 0.3, top_p 0.95);
                   опыты помечены id записей, а не местом G0, G1, ...
    evolib         ответ первой попытки подменён ответом большинства до вердикта группы (так делал старый
                   решатель с vote=True): её балл всегда 1, лучшая — всегда первая
    evolib_judge   то же; судья после всех попыток группы, а не после каждой
    ace_bo2        кандидаты рефлектора при T = 0, а не 0.7 (сравнивать с tools/ref_variants.json)
    scope, scope_bo2, scope_code, scope_k2
                   strategic через два перевода строки, а не один; синтезатор видит роль задачи и strategic,
                   без подсказки среды и tactical попытки (SC4)"""
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
hybrids = importlib.import_module("ace.methods.hybrids")
scope_show = importlib.import_module("ace.methods.scope").StrategicRules
scope_extract = importlib.import_module("ace.extract.scope")


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


def old_scope(name):
    def make():
        if not getattr(scope_show, "old", False):
            show = scope_show.prompt

            def prompt(self, ex, memory, item, k):
                p = show(self, ex, memory, item, k)
                p.system = "\n" + p.system if p.system else p.system
                return p
            scope_show.prompt, scope_show.old = prompt, True
            scope_extract.agent_context = lambda ex, attempt, book: dict(
                agent_name=f"{ex.task.name}_agent", agent_role=ex.task.system, task=attempt.question,
                current_system_prompt=f"{ex.task.system}\n\n{attempt.prompt.system.removeprefix(chr(10) * 2)}".strip())
        return METHODS[name]
    return make


OLD = {"tfgrpo": old_tfgrpo,
       "evolib": lambda: swap(evolib.evolib, group_verdict=old_vote),
       "evolib_judge": lambda: swap(evolib.evolib_judge, verdict=verdict.none, group_verdict=old_judge),
       "ace_bo2": lambda: swap(hybrids.ace_bo2, extract=hybrids.BestOf(hybrids.Reflector(), 2, hybrids.one_of_two)),
       **{name: old_scope(name) for name in ("scope", "scope_bo2", "scope_code", "scope_k2")}}

out, names = sys.argv[1], sys.argv[2:] or list(OLD)
for name in names:
    METHODS[name] = OLD[name]()
sys.argv = ["trace.py", out, *names]
runpy.run_path(str(root / "tools" / "trace.py"), run_name="__main__")
