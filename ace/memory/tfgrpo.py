"""Память Training-Free GRPO (youtu-agent: utu/practice/experience_updater.py; промпты tfgrpo_*.j2 дословно):
библиотека опытов «Experience name: Brief description.». Раз в батч план по всем операциям батча (_batch_update,
до 3 попыток разобрать JSON), код применяет ADD / UPDATE / DELETE, UPDATE неизвестного id добавляет опыт.

Опыты нумеруются по месту: G0, G1, ... — так апстрим раздаёт ключи после каждого батча; модель видит эти
метки, память переводит их в свои id."""
from .. import parse, render
from ..extract import OPERATIONS
from ..upstream.tfgrpo import ask
from ..model import Reader
from . import Lessons

PLAN_RETRIES = 3            # повторы плана батча, пока JSON не разберётся
PLAN = Reader(text=parse.json_block)


class Library(Lessons):
    requires = frozenset({OPERATIONS})

    def __init__(self):
        super().__init__("experience")

    def learn(self, ex, extractions):
        ops = [op for x in extractions for op in x.extras[OPERATIONS] if isinstance(op, dict)]
        plan = None
        for _ in range(PLAN_RETRIES):
            plan = ask(ex, "batch_experience_update_template", PLAN,
                       experiences_and_operations=render.batch_table(self.records(), ops))
            if plan is not None:
                break
        ids = {render.label(i): r.id for i, r in enumerate(self.records())}
        # метки модели -> id памяти; чужая метка не находит записи: UPDATE по ней добавляет опыт, DELETE пропускается
        self.apply([dict(p, id=ids.get(str(p.get("id")), "")) for p in plan if isinstance(p, dict)]
                   if isinstance(plan, list) else [], missing="add")
