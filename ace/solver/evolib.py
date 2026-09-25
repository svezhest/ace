"""Решатель EvoLib апстрима целиком (EvoLib/EvoLib: evolib_agent.py _sample_from_library и run_iteration,
eval_main.py HMMT_SOLVER_PROMPT; промпты evolib_solver.j2, evolib_instruction_hmmt.j2, evolib_format_hmmt.j2 дословно).

Выборка из библиотеки на каждую попытку: одно случайное число p; p < 0.4 и skills есть — до 10 skills, иначе p < 0.7
и insights есть — до 10 insights, иначе ничего; выборка с возвращением по весу (random.choices) — тот же расход
генератора, что у апстрима. Вес: skill — w_IG * max(IG, eps) + (среднее fig или 0.5), при w_IG от 100 без Future IG;
insight — max(среднее fig или 0.5, eps).

Решатель — одно сообщение user: инструкция, «Problem: ...», раздел выборки (skills или insights строками после
вступления), формат решения подзадачами; параметры — llm_params задачи; ответ модели без пробелов по краям
(LLMAgent.generate) — решение попытки целиком. Ответ в зачёт у hmmt — первый <answer>...</answer> без $, как в
run_iteration; у задач стенда (S2) — роль задачи, та же просьба решать подзадачами, инструкция задачи и строка
FINAL ANSWER."""
import random

import numpy as np

from .. import parse, prompts
from ..extract.evolib import EPS, generate, llm_params
from ..loop import Prompt, Solver
from ..model import Call, messages
from ..tasks import final_answer, variant
from . import OwnSolver

K, W_IG = 10, 1.0
LEGACY_W_IG = 100           # при w_IG от 100 апстрим не прибавляет Future IG к весу skill («legacy defaults»)
FIG_PRIOR = 0.5             # Future IG записи, которая ещё ни разу не была в промпте лучшей попытки
P_SKILLS, P_INSIGHTS = 0.4, 0.7     # накопленные вероятности веток показа
SOLVER = prompts.load("evolib_solver")
INTRO = {"skills": prompts.text("evolib_skills_intro"), "insights": prompts.text("evolib_insights_intro")}


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

    def __init__(self, k=K, w_ig=W_IG, temperature=None):
        self.k, self.w_ig, self.temperature = k, w_ig, temperature

    def sample(self, memory):
        """-> (skills, insights): _sample_from_library апстрима."""
        p = random.random()
        skills, insights = memory.skills.records(), memory.insights.records()
        if skills and p < P_SKILLS:
            weights = [skill_weight(r, self.w_ig) for r in skills]
            return random.choices(skills, weights=weights, k=min(len(skills), self.k)), []
        if insights and p < P_INSIGHTS:
            weights = [insight_weight(r) for r in insights]
            return [], random.choices(insights, weights=weights, k=min(len(insights), self.k))
        return [], []

    def prompt(self, ex, memory, item, k):
        skills, insights = self.sample(memory)
        shown = skills or insights
        section = INTRO["skills" if skills else "insights"] + "\n".join(r.text for r in shown) if shown else ""
        instruction, form, answer = solver_texts(ex.task)
        user = SOLVER.fill(instruction=instruction, problem=item["context"], section=section, format=form)
        p = llm_params(ex.task)
        if self.temperature is not None:
            p["temperature"] = self.temperature(k)

        def call(note):
            return Call(messages(user), p)
        return Prompt(shown=[r.id for r in shown], temperature=p.get("temperature", 0), solver=Solver(call, answer, generate))


SAMPLER = Sampler()
