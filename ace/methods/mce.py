"""MCE (meta-context-engineering: mce/main.py, utils.py, prompts/meta_agent.py, prompts/base_agent.py).
Промпты ace/prompts/mce_*.j2: апстрим без кодовых интерфейсов, утилит и записи навыка в файл.

mce = Meta(базовый агент с файлами):
    мета        итерация = проход; в начале итерации мета-агент пишет навык (SKILL.md) по истории итераций:
                обзор навыков с train и val, evaluations, архив навыков (wrap.Meta); в конце прохода val, следующая
                итерация начинается с лучшей по val из пройденных (строго больше, при равенстве первая)
    память      файлы context/ (мир документов); их заводит и правит базовый агент по навыку файловыми
                инструментами, до 30 раундов; итоги батча (question, llm_answer, target, is_correct) — в data/
                только на чтение, только текущий батч (train.json под-итерации)
    показ       все файлы context/ (интерфейс get_context апстрим пишет сам агент кодом: не делаем)
    извлечение  нет: память читает сырое
    когда учится  батч 20; неполный батч применяется в конце прохода
Параметры scripts/train_symptom_diagnosis.sh: 3 итерации, train 50 батчами по 25, val 20; у нас 40 батчами
по 20 и val 10. Базовому агенту апстрима доступны ещё python, call_llm и эмбеддинги.

mce_ace = Meta(ACE): тот же мета-агент (промпт mce_meta_ace — про рефлектор и куратор ACE), навык идёт в
системные промпты рефлектора и куратора ACE. Нового в сравнении нет, кроме меты: ученик — ace как есть.
"""
from .. import fs, prompts, render
from ..extract import Raw
from ..learner import Learner, swap
from ..memory import Files
from ..show import Whole
from ..wrap import Meta
from .ace import ace

META, META_ACE, BASE = prompts.load("mce_meta"), prompts.load("mce_meta_ace"), prompts.load("mce_base")
BASE_SYSTEM = prompts.text("mce_base_system")

BATCH, ROUNDS, ITERATIONS = 20, 30, 3


def meta_agent(template):
    """author для Meta: навык по истории итераций; пустой ответ — навык прошлой итерации."""
    def author(ex, history):
        out = ex.model.run("", template.fill(task_instruction=render.task_instruction(ex.task),
                                             skill_database=render.skill_database(history),
                                             evaluations=render.evaluations(history), skills=render.skills(history))).output
        return (out or "").strip() or (history[-1].text if history else "")
    return author


class Context(Files):
    """Файлы context/ базового агента. На батче агент по навыку правит их инструментами; итоги батча — в data/."""
    def __init__(self, rounds=ROUNDS):
        super().__init__("context")
        self.rounds = rounds

    def learn(self, ex, extractions):
        groups = [x.group for x in extractions]
        data = Files("result")
        for i, g in enumerate(groups, 1):
            e = g.episodes[g.chosen]
            data.write(f"r{i}", render.result(e.ok, e.answer, g.target, g.question))
        prompt = BASE.fill(task_instruction=render.task_instruction(ex.task), skill=ex.learner.skill,
                           summary=render.train_summary(sum(bool(g.episodes[g.chosen].ok) for g in groups), len(groups)))
        files = fs.FS({"context": fs.Mount(self), "data": fs.Mount(data, "ro")})
        ex.model.run(BASE_SYSTEM, prompt, tools=fs.TOOLS, deps=files, rounds=self.rounds)


base = Learner("mce_base", memory=Context(), show=Whole(line=render.plain, sep="\n\n"), extract=Raw(), every=BATCH,
               flush=True, epochs=ITERATIONS)
mce = Meta(base, meta_agent(META), "mce")
mce_ace = Meta(swap(ace, epochs=ITERATIONS), meta_agent(META_ACE), "mce_ace")
