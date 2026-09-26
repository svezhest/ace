"""GEPA (gepa-ai/gepa d771eb21b5: api.py optimize с умолчаниями, README «Quick Start» на AIME).

gepa = Evolution(ученик) — метод апстрима целиком:
    мета        пул кандидатов с оценками по вопросам val и Парето-фронтом; итерация — родитель с фронта (без
                доминируемых, с весом по числу вопросов), минибатч из перемешанного по эпохам train; потомок снова
                решает минибатч и входит в пул, если верных строго больше, — тогда он решает весь val; обучение — до
                бюджета вызовов метрики (wrap/gepa.py: Evolution)
    решатель    DefaultAdapter: системный промпт — текст кандидата, user — вход задачи, без параметров; в зачёт у
                aime — весь ответ (solver/gepa.py)
    вердикт     верный ответ (ContainsAnswerEvaluator — проверка задачи aime)
    извлечение  рефлексия на минибатче: вход, ответ и отзыв с верным ответом и решением по каждому вопросу, новый
                текст из ```-блока (extract/gepa.py)
    память      текст системного промпта (memory/gepa.py: Instruction); до рефлексии — seed задачи
    когда учится  на каждом минибатче (reflection_minibatch_size 3); минибатч родителя весь верен — рефлексии нет
    протокол    офлайн: val — весь, в пул; тест — лучшим по val кандидатом (result.best_candidate)
Умолчания optimize: candidate_selection_strategy pareto, frontier_type instance, module_selector round_robin (компонент
один), acceptance strict_improvement, use_merge False, seed 0; max_metric_calls 150 — как в квикстарте."""
from ..extract.gepa import Reflection
from ..learner import Learner
from ..loop import Protocol
from ..memory.gepa import Instruction
from ..solver.gepa import ADAPTER
from ..wrap.gepa import Evolution

MINIBATCH = 3               # reflection_minibatch_size
MAX_METRIC_CALLS = 150      # бюджет квикстарта
SEED = 0

# проходов не больше бюджета: итерация тратит минимум минибатч вызовов, обучение кончает Evolution
PROTOCOL = Protocol(offline=True, epochs=MAX_METRIC_CALLS)

gepa = Evolution(Learner("gepa", memory=Instruction(), solver=ADAPTER, extract=Reflection(), every=MINIBATCH,
                         protocol=PROTOCOL), MAX_METRIC_CALLS, SEED)
