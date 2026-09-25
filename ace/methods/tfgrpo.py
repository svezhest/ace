"""Training-Free GRPO (youtu-agent: utu/practice/training_free_grpo.py, experience_updater.py). Промпты
utu/prompts/practice/experience.yaml дословно в ace/prompts/tfgrpo_*.j2, параметры из
configs/practice/math_reasoning.yaml и configs/agents/practice/math_agent.yaml.

    попытки     в зачёт итоговый агент апстрима: T = 0.3, top_p 0.95; группа для обучения — G = 5 попыток
                при T = 0.7 (rollout_temperature)
    вердикт     верный ответ, награда 0/1
    извлечение  контраст (extract/tfgrpo.py): сводки -> групповое преимущество -> не больше 1 опыта -> сверка
                с библиотекой -> операции
    память      библиотека опытов «Experience name: Brief description.»; раз в батч план по всем операциям
                батча (_batch_update, до 3 попыток разобрать JSON), код применяет ADD / UPDATE / DELETE, UPDATE
                неизвестного id добавляет опыт; неполный батч отбрасывается
    показ       вся библиотека: «When solving problems, you MUST first carefully read ...», «[G0]. опыт»

Опыты нумеруются по месту: G0, G1, ... — так апстрим раздаёт ключи после каждого батча; модель видит эти
метки, память переводит их в свои id. Батч в апстриме 50 из 100 задач, 2 шага за эпоху; у нас 20 из 40."""
from .. import parse, prompts, render
from ..extract import OPERATIONS
from ..extract.tfgrpo import Contrast, ask
from ..learner import Learner
from ..loop import Attempts, first
from ..memory import Lessons
from ..show import Whole

GROUP, TEMPERATURE = 5, 0.7         # grpo_n, rollout_temperature
SCORED_TEMPERATURE, TOP_P = 0.3, 0.95   # итоговый агент апстрима (math_agent.yaml)
BATCH = 20
PLAN_RETRIES = 3            # повторы плана батча, пока JSON не разберётся


class Library(Lessons):
    requires = frozenset({OPERATIONS})

    def __init__(self):
        super().__init__("experience")

    def learn(self, ex, extractions):
        ops = [op for x in extractions for op in x.extras[OPERATIONS] if isinstance(op, dict)]
        plan = None
        for _ in range(PLAN_RETRIES):
            plan = parse.json_block(ask(ex, "batch_experience_update_template",
                                        experiences_and_operations=render.batch_table(self.records(), ops)))
            if plan is not None:
                break
        ids = {render.label(i, r): r.id for i, r in enumerate(self.records())}
        # метки модели -> id памяти; чужая метка не находит записи: UPDATE по ней добавляет опыт, DELETE пропускается
        self.apply([dict(p, id=ids.get(str(p.get("id")), "")) for p in plan if isinstance(p, dict)]
                   if isinstance(plan, list) else [], missing="add")


def temperature(k):
    return SCORED_TEMPERATURE if k == 0 else TEMPERATURE


def top_p(k):
    return TOP_P if k == 0 else None


EXPERIENCES = Whole(layout=lambda recs, memory: render.experiences(recs), head="",
                    before=prompts.text("tfgrpo_experiences_intro"))

tfgrpo = Learner("tfgrpo", memory=Library(), show=EXPERIENCES, extract=Contrast(),
                 attempts=Attempts(1 + GROUP, temperature, top_p, first), every=BATCH)
