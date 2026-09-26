"""Решатель EvoLib апстрима целиком (EvoLib/EvoLib: evolib_agent.py _sample_from_library и run_iteration,
eval_main.py HMMT_SOLVER_PROMPT; промпты evolib_solver.j2, evolib_instruction_hmmt.j2, evolib_format_hmmt.j2 дословно).

Выборка из библиотеки на каждую попытку: одно случайное число p; p < 0.4 и skills есть — до 10 skills, иначе p < 0.7
и insights есть — до 10 insights, иначе ничего; выборка с возвращением по весу (random.choices) — тот же расход
генератора, что у апстрима. Вес: skill — w_IG * max(IG, eps) + (среднее fig или 0.5), при w_IG от 100 без Future IG;
insight — max(среднее fig или 0.5, eps).

Решатель — одно сообщение user: инструкция, «Problem: ...», раздел выборки (skills или insights строками после
вступления), формат решения подзадачами; параметры — llm_params задачи; ответ модели без пробелов по краям
(LLMAgent.generate) — решение попытки целиком. Ответ решателя у hmmt — первый <answer>...</answer> без $, как в
run_iteration (по нему голосует vote; в зачёт у hmmt весь текст решения — tasks.WHOLE_REPLY); у задач стенда (S2) —
роль задачи, та же просьба решать подзадачами, инструкция задачи и строка FINAL ANSWER."""
import random

import numpy as np

from .. import parse, prompts, render
from ..upstream.evolib import EPS, generate, llm_params
from ..loop import Prompt, Solver
from ..model import Call, messages
from ..tasks import final_answer, variant
from . import OwnSolver

K = 10                      # записей в выборке
W_IG = 1.0                  # вес IG в весе skill
LEGACY_W_IG = 100           # при w_IG от 100 апстрим не прибавляет Future IG к весу skill («legacy defaults»)
FIG_PRIOR = 0.5             # Future IG записи, которая ещё ни разу не была в промпте лучшей попытки
P_SKILLS = 0.4              # накопленные вероятности веток показа: skills, затем insights
P_INSIGHTS = 0.7
SOLVER = prompts.load("evolib_solver")
SKILLS_INTRO = prompts.text("evolib_skills_intro")
INSIGHTS_INTRO = prompts.text("evolib_insights_intro")


def future(r):
    return np.mean(r.outcomes) if r.outcomes else FIG_PRIOR


def skill_weight(r, w_ig=W_IG):
    w = w_ig * max(r.ig, EPS)
    return w + future(r) if w_ig < LEGACY_W_IG else w


def insight_weight(r):
    return max(future(r), EPS)


def upstream_answer(text):
    """Ответ попытки run_iteration: первый <answer>...</answer> без $ ("" — нет)."""
    return parse.between(text or "", "<answer>", "</answer>").replace("<answer>", "").replace("$", "").strip()


def solver_texts(task):
    """(инструкция, формат, ответ в зачёт) решателя задачи."""
    if variant("evolib", task) == "math":
        return prompts.text("evolib_instruction_hmmt"), prompts.text("evolib_format_hmmt"), upstream_answer
    return (prompts.text("evolib_instruction", role=task.system, instr=task.instr), prompts.text("evolib_format"),
            final_answer)


class Sampler(OwnSolver):
    """k записей ветки, вес skill с w_ig; temperature(k) — температура попытки k (ступень абляции), None — нет."""
    random = True
    reads = ("skills", "insights")

    def __init__(self, k=K, w_ig=W_IG, temperature=None):
        self.k = k
        self.w_ig = w_ig
        self.temperature = temperature

    def sample(self, memory):
        """-> (skills, insights): _sample_from_library апстрима."""
        roll = random.random()
        skills = memory.skills.records()
        insights = memory.insights.records()
        if skills and roll < P_SKILLS:
            weights = [skill_weight(r, self.w_ig) for r in skills]
            return random.choices(skills, weights=weights, k=min(len(skills), self.k)), []
        if insights and roll < P_INSIGHTS:
            weights = [insight_weight(r) for r in insights]
            return [], random.choices(insights, weights=weights, k=min(len(insights), self.k))
        return [], []

    def prompt(self, ex, memory, item, k):
        skills, insights = self.sample(memory)
        shown = skills or insights
        intro = SKILLS_INTRO if skills else INSIGHTS_INTRO
        section = render.section(intro, shown)
        instruction, form, answer = solver_texts(ex.task)
        user = SOLVER.fill(instruction=instruction, problem=item["question"], section=section, format=form)
        params = llm_params(ex.task)
        if self.temperature is not None:
            params["temperature"] = self.temperature(k)

        def call(note):         # заметки рефлектора у EvoLib нет
            return Call(messages(user), params)
        solver = Solver(call, answer, generate)
        return Prompt(shown=[r.id for r in shown], temperature=params.get("temperature", 0), solver=solver)


SAMPLER = Sampler()
