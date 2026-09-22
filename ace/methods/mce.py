"""MCE (meta-context-engineering: mce/main.py, utils.py, prompts/meta_agent.py, prompts/base_agent.py).
Промпты prompts/mce_*.txt: апстрим без кодовых интерфейсов, утилит и записи навыка в файл.

    1 память      файлы context/, их заводит и правит базовый агент
    2 инжект      все файлы context/ (интерфейс get_context у апстрима пишет сам агент кодом: не делаем)
    3 сигнал      верный ответ; базовому агенту идут только итоги (question, llm_answer, target, is_correct)
    4 обновление  итерация = проход по train батчами по 20 (every, flush); reflect: keep;
                  curate: chain(iteration — в начале итерации мета-агент ask пишет SKILL.md по истории,
                  base — curate.tools: агент по навыку правит context/, итоги батча в data/ только на чтение);
                  bound: best_by_val — в конце итерации val, следующая стартует с лучшей по val
                  (строго >, при равенстве ранняя; итерация 0 — пустой контекст)
    решатель      общий

Параметры scripts/train_symptom_diagnosis.sh: 3 итерации, train 50 батчами по 25, val 20;
у нас 40 батчами по 20 и val 10. Базовому агенту апстрима доступны ещё python, call_llm и эмбеддинги.
"""
from .. import bound, curate, inject, prompts, reflect
from ..feedback import Feedback
from ..loop import Method
from ..memory import ALL
from ..update import Update, ask

META, BASE = prompts.load("mce_meta.txt"), prompts.load("mce_base.txt")

# 1. память

MEMORY = {"context": ALL}

# 4. обновление

BATCH, ROUNDS = 20, 30

meta = ask(META, curate.meta_fields, then=curate.new_skill)
base = curate.tools(BASE, curate.skill_fields, curate.context_and_results, rounds=ROUNDS,
                    system="You are a context engineer working with file tools.")

mce = Method("mce", MEMORY, inject.full(inject.plain, sep="\n\n"), Feedback("golden"),
             Update(reflect.keep, curate.chain(curate.iteration(meta), base), bound.best_by_val(), every=BATCH, flush=True), epochs=3)
