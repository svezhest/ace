"""Трасса новых методов с настройками старого кода там, где новый код сознательно решает иначе (DEVIATIONS.md):
так видно, что всё остальное совпадает с эталоном tools/ref_trace.json.
    uv run python tools/as_old.py OUT.json [method ...] && uv run python tools/compare.py OUT.json

    tfgrpo         в зачёт жадная попытка при T = 0, а не итоговый агент апстрима (T = 0.3, top_p 0.95);
                   опыты помечены id записей, а не местом G0, G1, ...; группа без top_p, обновление при T = 0,
                   цели без перевода строки в конце (TF6)
    evolib         ответ первой попытки подменён ответом большинства до вердикта группы (так делал старый
                   решатель с vote=True): её балл всегда 1, лучшая — всегда первая
    evolib_judge   то же; судья после всех попыток группы, а не после каждой
    ace_bo2        кандидаты рефлектора при T = 0, а не 0.7 (сравнивать с tools/ref_variants.json)
    ace_group      контраст TF-GRPO как в старом коде (цели и T = 0, TF6); сравнивать с tools/ref_variants.json
    scope, scope_bo2, scope_code, scope_k2
                   ответы SCOPE по старым схемам pydantic (фиктивная модель заполняет схему, разбор получает её
                   JSON), а не текстом: на тексте фиктивной модели синтезатор правил не находит;
                   strategic через два перевода строки, а не один; синтезатор видит роль задачи и strategic,
                   без подсказки среды и tactical попытки (SC3)"""
import importlib
import json
import runpy
import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))
from pydantic import BaseModel  # noqa: E402

from ace import loop, model, render, verdict  # noqa: E402
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
    old_contrast()
    return swap(tfgrpo.tfgrpo, attempts=Attempts(1 + tfgrpo.GROUP, lambda k: 0 if k == 0 else tfgrpo.TEMPERATURE,
                                                 pick=greedy))


def old_contrast():
    """Контраст TF-GRPO как в старом коде: цели без перевода строки в конце, вызовы при T = 0 (TF6)."""
    contrast = importlib.import_module("ace.extract.tfgrpo")
    for k in contrast.OBJECTIVE:
        contrast.OBJECTIVE[k] = contrast.OBJECTIVE[k].rstrip("\n")
    contrast.LEARNING = contrast.LEARNING.rstrip("\n")
    run = contrast.ask

    def ask(ex, name, **fields):
        model, ex.model = ex.model, Zero(ex.model)
        try:
            return run(ex, name, **fields)
        finally:
            ex.model = model
    contrast.ask = tfgrpo.ask = ask


class Zero:
    """Модель, у которой вызов без температуры идёт при T = 0 (так звал обновление старый код)."""
    def __init__(self, model):
        self.model = model

    def run(self, *args, temperature=None, **kw):
        return self.model.run(*args, temperature=0 if temperature is None else temperature, **kw)


def first_is_vote(ex, group):
    group.episodes[0].answer = verdict.majority(e.answer for e in group.episodes)


def old_vote(ex, group):
    first_is_vote(ex, group)
    verdict.vote(ex, group)


def old_judge(ex, group):
    first_is_vote(ex, group)
    for e in group.episodes:
        verdict.judge(ex, e, "")


# старые схемы ответов SCOPE: фиктивная модель заполняет их, как раньше


class Proposal(BaseModel):
    update_text: str = ""
    rationale: str = ""
    confidence: str = "medium"


class Selection(BaseModel):
    selected_index: int = 0


class Classification(BaseModel):
    is_duplicate: bool = False
    scope: str = "tactical"
    confidence: float | None = None
    domain: str = "general"


class Analysis(BaseModel):
    consolidation: list[list[int]] = []
    subsumption: list[list[int]] = []
    conflicts: list[list[int]] = []


class Rule(BaseModel):
    rule: str
    rationale: str = ""


class Subsumed(BaseModel):
    subsumed: bool = False


SCHEMAS = {"analyzing agent execution": Proposal, "evaluating multiple candidate": Selection,
           "You are a rule classifier": Classification, "rule optimization analyzer": Analysis,
           "merging similar rules": Rule, "resolving a conflict": Rule, "subsumes the specific": Subsumed}


class BySchema:
    """Модель, которая на промпты SCOPE отвечает JSON старой схемы."""
    def __init__(self, inner):
        self.inner = inner

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def run(self, system, user, output=str, **kw):
        schema = next((sc for marker, sc in SCHEMAS.items() if marker in user), None) if output is str else None
        if schema is None:
            return self.inner.run(system, user, output=output, **kw)
        r = self.inner.run(system, user, output=schema, **kw)
        text = json.dumps(r.output.model_dump()) if r.output is not None else ""
        return model.Reply(text, text, False, [])


def old_scope(name):
    def make():
        if not getattr(scope_show, "old", False):
            init = loop.Experiment.__init__
            loop.Experiment.__init__ = lambda self, task, learner, m: init(self, task, learner, BySchema(m))
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


def old_group():
    old_contrast()
    return hybrids.ace_group


OLD = {"tfgrpo": old_tfgrpo,
       "ace_group": old_group,
       "evolib": lambda: swap(evolib.evolib, group_verdict=old_vote),
       "evolib_judge": lambda: swap(evolib.evolib_judge, verdict=verdict.none, group_verdict=old_judge),
       "ace_bo2": lambda: swap(hybrids.ace_bo2, extract=hybrids.BestOf(hybrids.Reflector(), 2, hybrids.one_of_two)),
       **{name: old_scope(name) for name in ("scope", "scope_bo2", "scope_code", "scope_k2")}}

out, names = sys.argv[1], sys.argv[2:] or list(OLD)
for name in names:
    METHODS[name] = OLD[name]()
sys.argv = ["trace.py", out, *names]
runpy.run_path(str(root / "tools" / "trace.py"), run_name="__main__")
