"""Драйвер записи SCOPE (JarvisPei/SCOPE 4dc0da5) на живой модели.

В апстриме SCOPE — библиотека: агента, бенчмарка и чекера нет. Агентный цикл вокруг неё — наша обвязка, та же, что
у метода scope стенда (DEVIATIONS SC2): цикл ace.loop, решатель S1, задачи и проверки стенда, run_python в
песочнице (docker). SCOPE зовётся как есть, по examples/basic_usage.py: strategic правила — в начале задачи
(get_strategic_rules_for_agent), после каждого шага — on_step_complete, принятое правило дописывается к системному
промпту агента ("\\n\\n## Learned Guideline:\\n" + текст). Шаг — вызов инструмента (посреди попытки) и итоговый
ответ (после неё); что агент сообщает о шаге (вывод, вызов, наблюдение, ошибка с именем типа) — поля обвязки, те же,
что у нашего SCOPE (ace/extract/scope.py). Модель SCOPE — create_openai_model(base_url) без параметров запроса.

Варианты (VARIANTS):
    scope       formula, 5 задач; max_rules_per_task 3 и max_strategic_rules_per_domain 3; strategic память
                прошлых прогонов — seed_rules.json (по 3 правила на домен, о другой работе — веб-поиске, чтобы
                классификатор не счёл новое правило дублем: новое strategic правило зовёт оптимизатор домена)
    scope_code  formula с run_python в песочнице, 2 задачи
    scope_bo2   use_best_of_n, candidate_models — та же модель с temperature 0.7; 2 задачи
    scope_k2    два оптимизатора (efficiency, thoroughness), у попытки k — агент со своим; в зачёт лучшая по
                метке; 2 задачи

usage (из корня стенда; запись — tools.record.record с --seed на PORT):
    PYTHONPATH=/Users/user/Projects/upstreams/SCOPE uv run python bridge/live/scope/driver.py VARIANT OUT \\
        --base-url http://127.0.0.1:PORT/v1
В OUT: log.json и summary.json цикла, steps.json — память после каждой задачи, exp/<перспектива>/ — exp_path SCOPE
(strategic_memory/global_rules.json, prompt_updates/)."""
import argparse
import asyncio
import json
import shutil
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from scope import SCOPEOptimizer  # noqa: E402
from scope.models import create_openai_model  # noqa: E402

from ace import render  # noqa: E402
from ace.env import Env, Sandbox  # noqa: E402
from ace.learner import Learner  # noqa: E402
from ace.loop import Attempts, Prompt, best, first, run  # noqa: E402
from ace.model import Model, Patch  # noqa: E402
from ace.tasks import TASKS  # noqa: E402

HERE = Path(__file__).parent
MODEL = "ornith15-9b"
GUIDELINE = "\n\n## Learned Guideline:\n"

VARIANTS = {
    "scope": dict(n=5, seed=HERE / "seed_rules.json", options=dict(max_rules_per_task=3, max_strategic_rules_per_domain=3)),
    "scope_code": dict(n=2, env=Sandbox()),
    "scope_bo2": dict(n=2, best_of=True),
    "scope_k2": dict(n=2, modes=("efficiency", "thoroughness")),
}

# SCOPE асинхронный, цикл стенда — нет: корутины идут в одном фоновом цикле событий (клиент openai живёт в нём)
LOOP = asyncio.new_event_loop()
threading.Thread(target=LOOP.run_forever, daemon=True).start()


def wait(coro):
    return asyncio.run_coroutine_threadsafe(coro, LOOP).result()


def error(failed):
    """(тип, сообщение) обвязки -> исключение с этим именем типа (on_step_complete берёт type(error).__name__)."""
    return type(failed[0], (Exception,), {})(failed[1]) if failed else None


@dataclass
class Library(Learner):
    """Ученик-обвязка: цикл стенда зовёт хуки, хуки зовут SCOPE апстрима. optimizers[k] — SCOPE агента попытки k."""
    optimizers: list = field(default_factory=list)
    steps: list = field(default_factory=list)       # память после каждой задачи
    current: dict = field(default_factory=dict)     # k -> системный промпт агента сейчас (None — как при запуске)

    def __deepcopy__(self, memo):
        return self                 # прогон один; клиенты модели не копируются

    def watches_steps(self):
        return True

    def agent(self, ex):
        return f"{ex.task.name}_agent"

    def task_id(self, ex):
        return f"{ex.task.name}_{ex.i}"

    def prompt(self, ex, item, k, memory=None):
        """Начало задачи: базовый промпт (роль задачи и подсказку среды ставит цикл) + strategic правила."""
        self.current[k] = None
        p = Prompt(self.optimizers[k].get_strategic_rules_for_agent(self.agent(ex)))
        p.temperature, p.top_p = self.attempts.temperature(k), self.attempts.top_p(k)
        return p

    def step(self, ex, k, system, question, **fields):
        """on_step_complete; принятое правило дописывается к системному промпту агента."""
        current = self.current.get(k) or system
        r = wait(self.optimizers[k].on_step_complete(agent_name=self.agent(ex), agent_role=ex.task.system, task=question,
                                                     current_system_prompt=current, task_id=self.task_id(ex), **fields))
        if r:
            self.current[k] = current + GUIDELINE + r[0]
        return r

    def on_step(self, ex, attempt, step):
        if not attempt.training:
            return None
        r = self.step(ex, attempt.k, attempt.system, attempt.question, tool_calls=render.tool_call(step.tool, step.args),
                      observations=step.result, error=error(render.tool_error(step.result) if step.failed else None))
        return Patch(system=self.current[attempt.k]) if r else None

    def on_question(self, ex, group):
        """Итоговый шаг каждой попытки: попытка в зачёт, затем остальные."""
        eps = [group.episodes[group.chosen]] + [e for i, e in enumerate(group.episodes) if i != group.chosen]
        for e in eps:
            failed = (render.incorrect_answer(e.answer, e.target) if e.ok is False else
                      render.truncated_answer() if e.truncated else None)
            self.step(ex, e.k, e.system, e.question, model_output=e.output, observations=render.answer_seen(e.ok),
                      error=error(failed))
        self.steps.append(self.state(ex))

    def state(self, ex):
        """Память SCOPE по перспективам: strategic на диске, tactical задачи, принято за прогон."""
        agent, out = self.agent(ex), []
        for o in self.optimizers:
            path = Path(o.strategic_store.global_rules_path)
            strategic = json.loads(path.read_text()).get(agent, {}) if path.exists() else {}
            tactical = [r["rule"] for r in o._applied_rules_by_task.get(self.task_id(ex), {}).get(agent, [])]
            out.append(dict(strategic=strategic, tactical=tactical, accepted=o._applied_rules_count.get(agent, 0)))
        return out

    def dump(self):
        return self.steps[-1] if self.steps else []


def optimizer(mode, path, base_url, v):
    if v.get("seed"):
        (path / "strategic_memory").mkdir(parents=True, exist_ok=True)
        shutil.copy(v["seed"], path / "strategic_memory" / "global_rules.json")
    extra = dict(v.get("options", {}))
    if v.get("best_of"):
        extra.update(use_best_of_n=True,
                     candidate_models=[create_openai_model(MODEL, api_key="x", base_url=base_url, temperature=0.7)])
    return SCOPEOptimizer(create_openai_model(MODEL, api_key="x", base_url=base_url), exp_path=str(path),
                          synthesis_mode=mode, store_history=True, **extra)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("variant", choices=VARIANTS)
    ap.add_argument("out", type=Path)
    ap.add_argument("--base-url", required=True)
    a = ap.parse_args()
    v = VARIANTS[a.variant]
    modes = v.get("modes", ("thoroughness",))
    learner = Library(a.variant, env=v.get("env", Env()), attempts=Attempts(len(modes), pick=best if len(modes) > 1 else first),
                      optimizers=[optimizer(m, a.out / "exp" / m, a.base_url, v) for m in modes])
    summary = run(TASKS["formula"], learner, Model(MODEL, a.base_url, backend="wire"), v["n"], str(a.out))
    json.dump(learner.steps, open(a.out / "steps.json", "w"), ensure_ascii=False, indent=1)
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
