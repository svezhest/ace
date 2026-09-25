"""Эталоны Training-Free GRPO (youtu-agent, utu/practice/experience_updater.py).

usage: .venvs/youtu/bin/python bridge/capture_tfgrpo.py
Пишет bridge/fixtures/tfgrpo/{config,prompts,parsers,memory,loop}.json. Updater грузится через шим из
repro/tfgrpo_run.py:58-140 (utu целиком не нужен); config.json снимается в подпроцессе настоящим utu.
"""
import asyncio
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import types
from contextlib import contextmanager
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fake  # noqa: E402

REPO = os.path.join(fake.UPSTREAMS, "youtu-agent")
PROMPTS_DIR = os.path.join(REPO, "utu", "prompts")
METHOD = "tfgrpo"
UTU_ENV = {"UTU_LLM_TYPE": "chat.completions", "UTU_LLM_MODEL": "fake",
           "UTU_LLM_BASE_URL": "http://fake.invalid/v1", "UTU_LLM_API_KEY": "fake",
           "JUDGE_LLM_TYPE": "chat.completions", "JUDGE_LLM_MODEL": "fake",
           "JUDGE_LLM_BASE_URL": "http://fake.invalid/v1", "JUDGE_LLM_API_KEY": "fake"}


# --- config.json: настоящий utu, загрузчик конфигов и TrainingFreeGRPO.build --------------------

def capture_config():
    import pathlib

    sys.path.insert(0, REPO)
    from utu.config import ConfigLoader
    from utu.practice import training_free_grpo as tfg

    class NoDB:
        def __init__(self, *a, **k):
            pass

        def check_dataset(self, name):
            return True

    class Rollouts:
        def __init__(self, config, batch_size):
            self.config = config

    tfg.TrainingFreeGRPODataManager = NoDB
    tfg.RolloutManager = Rollouts
    out = {}
    for name in ("math_reasoning", "web_search"):
        cfg = ConfigLoader.load_training_free_grpo_config(name)
        agent_model = cfg.evaluation.agent.model
        before = {"agent_temperature": agent_model.model_settings.temperature,
                  "agent_top_p": agent_model.model_settings.top_p}
        # do_eval в конфигах выключен; включаем, чтобы увидеть температуру eval-прогона
        cfg.practice.do_eval = True
        grpo = tfg.TrainingFreeGRPO(cfg)
        asyncio.run(grpo.build())
        practice_model = grpo.practice_rollout_manager.config.agent.model
        eval_model = grpo.eval_rollout_manager.config.agent.model
        # итоговый конфиг агента с опытом; пишется в DIR_ROOT/configs/agents/practice — уводим в tmp
        root = pathlib.Path(tempfile.mkdtemp())
        (root / "configs" / "agents" / "practice").mkdir(parents=True)
        tfg.DIR_ROOT = root
        path = grpo._create_agent_config_with_experiences({"G0": "Units: check units.", "G1": "Verify: recompute."})
        out[name] = {
            "practice": cfg.practice.model_dump(),
            "evaluation_pass_k": cfg.evaluation.pass_k,
            "loaded": before,
            "after_build": {
                "original_temperature": grpo.original_temperature,
                "practice_rollout_temperature": practice_model.model_settings.temperature,
                "eval_rollout_temperature": eval_model.model_settings.temperature,
                "practice_and_eval_share_agent": grpo.practice_rollout_manager.config.agent
                is grpo.eval_rollout_manager.config.agent,
                "practice_pass_k": grpo.practice_rollout_manager.config.pass_k,
                "eval_pass_k": grpo.eval_rollout_manager.config.pass_k,
            },
            # параметры query_one у ExperienceUpdater: config.model.model_params
            "updater_query_params": cfg.evaluation.agent.model.model_params.model_dump(),
            "final_agent_yaml": open(path, encoding="utf-8").read(),
        }
    head = fake.header("youtu-agent", {
        "TrainingFreeGRPO.build": tfg.TrainingFreeGRPO.build,
        "TrainingFreeGRPO._create_agent_config_with_experiences": tfg.TrainingFreeGRPO._create_agent_config_with_experiences,
        "ConfigLoader.load_training_free_grpo_config": ConfigLoader.load_training_free_grpo_config,
    })
    head["note"] = ("do_eval принудительно True; TrainingFreeGRPODataManager и RolloutManager заменены "
                    "заглушками (без БД), DIR_ROOT для итогового yaml — tmp")
    head["command"] += "  (подпроцесс: capture_tfgrpo.py config)"
    fake.write(METHOD, "config", head, out)
    print(json.dumps(out["math_reasoning"]["updater_query_params"]))


# --- шим utu для experience_updater.py (repro/tfgrpo_run.py:58-140) -------------------------------

LLM = fake.FakeLLM()
PARAMS = []  # полные kwargs каждого query_one


def install_shims():
    @contextmanager
    def custom_span(_name):
        yield None

    agents = types.ModuleType("agents")
    agents.custom_span = custom_span
    sys.modules["agents"] = agents

    import jinja2
    import yaml
    from pydantic import BaseModel

    class FileUtils:
        # как utu/utils/path.py:75 и :108
        @staticmethod
        def load_prompts(name):
            with open(os.path.join(PROMPTS_DIR, name), encoding="utf-8") as f:
                return yaml.safe_load(f)

        @staticmethod
        def get_jinja_template_str(s):
            return jinja2.Template(s)

    class SimplifiedAsyncOpenAI:
        def __init__(self, **_kwargs):
            pass

        async def query_one(self, messages, **params):
            PARAMS.append(params)
            return LLM(messages, **params)

    class _Logger:
        def info(self, *a, **k):
            pass

        debug = info

        def warning(self, msg, *a, **k):
            LOG.append(str(msg))

        error = warning

    class EvaluationSample(BaseModel):
        raw_question: str = ""
        correct_answer: str = ""
        response: str = ""
        trajectories: str = "[]"
        reward: float = 0.0
        reasoning: str | None = None

    utu = types.ModuleType("utu")
    utu.__path__ = []
    cfg_mod = types.ModuleType("utu.config")
    cfg_mod.AgentConfig = object
    db_mod = types.ModuleType("utu.db")
    db_mod.EvaluationSample = EvaluationSample
    utils_mod = types.ModuleType("utu.utils")
    utils_mod.FileUtils = FileUtils
    utils_mod.SimplifiedAsyncOpenAI = SimplifiedAsyncOpenAI
    utils_mod.get_logger = lambda *a, **k: _Logger()
    practice_mod = types.ModuleType("utu.practice")
    practice_mod.__path__ = [os.path.join(REPO, "utu", "practice")]

    @dataclass
    class TaskRecorder:
        experiment_name: str = None
        experiences: dict = None
        stats: dict = None

        def experiences_update(self, experiences):
            self.experiences = experiences

        def stat_update(self, stat):
            self.stats = {**(self.stats or {}), **stat}

    prac_utils = types.ModuleType("utu.practice.utils")
    prac_utils.TaskRecorder = TaskRecorder

    for name, mod in [
        ("utu", utu), ("utu.config", cfg_mod), ("utu.db", db_mod), ("utu.utils", utils_mod),
        ("utu.practice", practice_mod), ("utu.practice.utils", prac_utils),
    ]:
        sys.modules[name] = mod

    path = os.path.join(REPO, "utu", "practice", "experience_updater.py")
    spec = importlib.util.spec_from_file_location("utu.practice.experience_updater", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["utu.practice.experience_updater"] = mod
    spec.loader.exec_module(mod)
    mod.EvaluationSample = EvaluationSample
    mod.TaskRecorder = TaskRecorder
    # as_completed по порядку создания: вызовы идут последовательно и детерминированно
    mod.asyncio = types.SimpleNamespace(Semaphore=asyncio.Semaphore, as_completed=lambda tasks: list(tasks))
    return mod


LOG = []
AGENT_OBJ = "input: A math question\noutput: A step-by-step reasoning process that leads to the final answer\n"
LEARN_OBJ = "Help the agent to improve the solving capability on math questions by extracting general and concise guidelines.\n"


def make_config(model_params):
    dump = dict(model_params)
    return types.SimpleNamespace(model=types.SimpleNamespace(
        model_provider=types.SimpleNamespace(model_dump=lambda: {"type": "chat.completions"}),
        model_params=types.SimpleNamespace(model_dump=lambda: dict(dump))))


def sample(EU, case, i, reward, answer="42", critique=None, traj=True):
    trajectories = json.dumps([{"agent": "math_agent", "trajectory": [
        {"role": "user", "content": f"Problem {case}"},
        {"role": "assistant", "content": f"attempt {i} of {case}: answer {'42' if reward else '41'}"},
    ]}]) if traj else ""
    return EU.EvaluationSample(raw_question=f"Problem {case}", correct_answer=answer, response=f"answer {i}",
                               trajectories=trajectories, reward=reward, reasoning=critique)


def case_of(text):
    m = re.search(r"Problem (\w+)", text)
    return m.group(1) if m else "?"


def ops_in(text):
    """JSON-операции из текста BATCH_..._UP (как их печатает _format_exp_and_ops)."""
    text = text.split("<Experiences and Proposed Operations>")[-1]
    dec, out, i = json.JSONDecoder(), [], 0
    while (i := text.find("\n{", i)) != -1:
        obj, i = dec.raw_decode(text, i + 1)
        out.append(obj)
    return out


def fenced(obj):
    return "```json\n" + json.dumps(obj, indent=2) + "\n```"


def reset():
    LLM.calls.clear()
    PARAMS.clear()
    LOG.clear()


def calls():
    out = []
    for c, p in zip(LLM.calls, PARAMS):
        out.append({"messages": c["messages"], "params": p, "matched": c["matched"], "response": c["response"]})
    return out


def run(coro):
    return asyncio.run(coro)


# --- уровни -----------------------------------------------------------------------------------------

def default_rules(group_ops=None):
    """Ответы по маркерам в пользовательском промпте каждого из четырёх шаблонов."""
    group_ops = group_ops or {}

    def summary(text):
        m = re.search(r"<Trajectory\n(.*?)\n</Trajectory>", text, re.S)
        return f"Summary of {case_of(text)}: {m.group(1)[-40:] if m else ''}"

    def advantage(text):
        c = case_of(text)
        return f"<Comparative Analysis>...</Comparative Analysis>\n<Experiences>\n1. Rule {c}: check the arithmetic of {c}.\n</Experiences>"

    def group_update(text):
        c = re.search(r"Rule (\w+):", text.split("<New Experiences>")[-1])
        c = c.group(1) if c else "?"
        default = [{"operation": "ADD", "id": None, "content": f"Rule {c}: check the arithmetic of {c}."}]
        return fenced(group_ops.get(c, default))

    def batch(text):
        return fenced(ops_in(text))

    return [("<Experiences and Proposed Operations>", batch), ("<Existing Experiences>", group_update),
            ("<Agent Input>", advantage), ("<Working Agent Input>", summary)]


def level_prompts(EU, cfg):
    """Все шаблоны в тех местах, где их рендерит updater; запросы записаны фейком."""
    upd = EU.ExperienceUpdater(cfg, AGENT_OBJ, LEARN_OBJ)
    LLM.rules = default_rules()
    out = {"templates": upd.prompts}
    Rec = EU.TaskRecorder
    cases = {}

    reset()
    rolls = [sample(EU, "A", 0, 1.0, critique="Correct."), sample(EU, "A", 1, 0.0)]
    run(upd._single_rollout_summary(rolls, concurrency=1, given_ground_truth=True))
    cases["summary_gt"] = calls()

    reset()
    run(upd._single_rollout_summary(rolls[:1], concurrency=1, given_ground_truth=False))
    cases["summary_no_gt"] = calls()

    reset()
    summarized = {"Problem A": [{"trajectory_summary": "S0", **rolls[0].model_dump()},
                                {"trajectory_summary": "S1", **rolls[1].model_dump()}]}
    run(upd._group_advantage(summarized, concurrency=1, given_ground_truth=True, num_experiences=2))
    cases["advantage_gt"] = calls()

    reset()
    run(upd._group_advantage(summarized, concurrency=1, given_ground_truth=False, num_experiences=1))
    cases["advantage_no_gt"] = calls()

    new = [{"experiences": "1. Rule A: check the arithmetic of A."}]
    reset()
    run(upd._group_update(Rec(), new, concurrency=1))
    cases["group_update_empty_library"] = calls()

    reset()
    run(upd._group_update(Rec(experiences={"G0": "Units: check units.", "G1": "Verify: recompute."}), new, concurrency=1))
    cases["group_update_library"] = calls()

    reset()
    crit = [{"operations": [{"operation": "UPDATE", "id": "G0", "content": "Units: check units twice."},
                            {"operation": "ADD", "id": None, "content": "Rule A: check the arithmetic of A."}]}]
    run(upd._batch_update(Rec(experiences={"G0": "Units: check units.", "G1": "Verify: recompute."}), crit))
    cases["batch_update"] = calls()

    reset()
    run(upd._batch_update(Rec(), [{"operations": []}]))
    cases["batch_update_no_ops"] = calls()

    out["requests"] = cases
    return out


GROUP_RESPONSES = {
    "fenced": fenced([{"operation": "ADD", "id": None, "content": "X: a."}]),
    "bare_json": json.dumps([{"operation": "ADD", "id": None, "content": "X: a."}]),
    "two_fences": fenced([{"operation": "ADD", "content": "first"}]) + "\nthen\n" + fenced([{"operation": "ADD", "content": "second"}]),
    "upper_JSON_fence": "```JSON\n[{\"operation\": \"ADD\", \"content\": \"X\"}]\n```",
    "plain_fence": "```\n[{\"operation\": \"ADD\", \"content\": \"X\"}]\n```",
    "truncated": "```json\n[{\"operation\": \"ADD\", \"content\": \"X",
    "no_closing_fence": "```json\n[{\"operation\": \"ADD\", \"content\": \"X\"}]",
    "object_not_list": fenced({"operation": "ADD", "content": "X"}),
    "prose_before": "Here is the plan:\n" + fenced([{"operation": "NONE", "id": None, "content": "X"}]) + "\nDone.",
}

ADVANTAGE_RESPONSES = {
    "one_tag": "<Experiences>\n1. A: a.\n</Experiences>",
    "two_tags": "<Experiences>\n1. first\n</Experiences>\n<Experiences>\n1. second\n</Experiences>",
    "no_closing": "<Experiences>\n1. A: a.\n",
    "lower_case": "<experiences>\n1. a\n</experiences>",
    "mixed_case": "<EXPERIENCES>  1. a  </Experiences>",
    "empty": "<Experiences>\n</Experiences>",
    "no_tag": "1. A: a.",
    "template_echo": "<Experiences>\n  [Extract AT MOST **1** experiences]\n  1. [experience 1]\n</Experiences>",
}


def level_parsers(EU, cfg):
    """Разбор <Experiences> (experience_updater.py:192) и ```json (:250, :298) самим updater."""
    upd = EU.ExperienceUpdater(cfg, AGENT_OBJ, LEARN_OBJ)
    Rec = EU.TaskRecorder
    out = {"advantage": {}, "group_update": {}, "batch_update": {}}
    for name, resp in ADVANTAGE_RESPONSES.items():
        LLM.rules = [("<Agent Input>", resp)]
        reset()
        rolls = {f"Problem {name}": [{"trajectory_summary": "S", "reward": 1.0, "raw_question": f"Problem {name}", "correct_answer": "1"},
                                     {"trajectory_summary": "S", "reward": 0.0, "raw_question": f"Problem {name}", "correct_answer": "1"}]}
        res = run(upd._group_advantage(rolls, concurrency=1, given_ground_truth=True, num_experiences=1))
        out["advantage"][name] = {"response": resp, "experiences": [r["experiences"] for r in res]}
    for name, resp in GROUP_RESPONSES.items():
        LLM.rules = [("<Existing Experiences>", resp)]
        reset()
        res = run(upd._group_update(Rec(), [{"experiences": "1. X"}], concurrency=1))
        out["group_update"][name] = {"response": resp, "operations": [r["operations"] for r in res],
                                     "dropped": len(res) == 0, "log": list(LOG)}
    for name, resp in GROUP_RESPONSES.items():
        LLM.rules = [("<Experiences and Proposed Operations>", resp)]
        reset()
        try:
            new = run(upd._batch_update(Rec(experiences={"G0": "old"}), [{"operations": [{"operation": "ADD", "content": "X"}]}]))
        except Exception as e:  # апстрим падает, например на объекте вместо списка
            new = {"error": f"{type(e).__name__}: {e}"}
        out["batch_update"][name] = {"response": resp, "experiences": new, "llm_calls": len(LLM.calls)}
    return out


PLANS = {
    "add_update_delete": [
        {"operation": "ADD", "id": None, "content": "New: a."},
        {"operation": "UPDATE", "id": "G1", "content": "Verify: recompute twice."},
        {"operation": "DELETE", "id": "G0", "content": "Units: check units."},
    ],
    "update_unknown_id_adds": [{"operation": "UPDATE", "id": "G9", "content": "Orphan: b."}],
    "delete_unknown_id": [{"operation": "DELETE", "id": "G9", "content": "x"}],
    "empty_content_skipped": [{"operation": "ADD", "content": ""}, {"operation": "DELETE", "id": "G0", "content": ""}],
    "missing_operation_is_add": [{"content": "Default: c."}],
    "none_operation_ignored": [{"operation": "NONE", "id": None, "content": "Same: d."}],
    "lowercase_operation_ignored": [{"operation": "add", "content": "lower"}],
    "int_id_not_matched": [{"operation": "UPDATE", "id": 0, "content": "int id"}],
    "delete_then_add_key": [{"operation": "DELETE", "id": "G0", "content": "x"}, {"operation": "ADD", "content": "A1"},
                            {"operation": "ADD", "content": "A2"}],
    "empty_plan": [],
}

FORMAT_CASES = {
    "no_ops": ({"G0": "a"}, []),
    "related_and_free": ({"G0": "a", "G1": "b"}, [{"operation": "UPDATE", "id": "G0", "content": "a2"},
                                                  {"operation": "ADD", "id": None, "content": "c"},
                                                  {"operation": "NONE", "content": "d"}]),
    "unknown_id_dropped": ({"G0": "a"}, [{"operation": "UPDATE", "id": "G7", "content": "x"}]),
    "empty_library": ({}, [{"operation": "ADD", "id": None, "content": "c"}]),
    "unicode": ({"G0": "π ≈ 3.14"}, [{"operation": "UPDATE", "id": "G0", "content": "π — число"}]),
}


def level_memory(EU, cfg):
    upd = EU.ExperienceUpdater(cfg, AGENT_OBJ, LEARN_OBJ)
    Rec = EU.TaskRecorder
    base = {"G0": "Units: check units.", "G1": "Verify: recompute."}
    out = {"batch_update": {}, "format_exp_and_ops": {}, "partial_filter": {}}
    for name, plan in PLANS.items():
        LLM.rules = [("<Experiences and Proposed Operations>", fenced(plan))]
        reset()
        new = run(upd._batch_update(Rec(experiences=dict(base)), [{"operations": [{"operation": "ADD", "content": "X"}]}]))
        out["batch_update"][name] = {"before": base, "plan": plan, "after": new}
    for name, (exps, ops) in FORMAT_CASES.items():
        out["format_exp_and_ops"][name] = {"experiences": exps, "operations": ops,
                                           "text": upd._format_exp_and_ops(exps, ops)}
    # фильтр групп 0 < avg < 1 и пустая траектория
    LLM.rules = default_rules()
    groups = {"mixed": [1, 0, 1, 0], "all_one": [1, 1, 1, 1], "all_zero": [0, 0, 0, 0], "one_of_four": [0, 0, 0, 1]}
    rolls = [sample(EU, c, i, float(r)) for c, rs in groups.items() for i, r in enumerate(rs)]
    # пустая строка trajectories выпадает до подсчёта среднего
    rolls += [sample(EU, "notraj", 0, 0.0, traj=False), sample(EU, "notraj", 1, 1.0), sample(EU, "notraj", 2, 0.0)]
    for gt in (True, False):
        reset()
        res = run(upd._single_rollout_summary(rolls, concurrency=1, given_ground_truth=gt))
        out["partial_filter"][f"given_ground_truth={gt}"] = {
            "rewards": groups, "summarized": {k: [r["reward"] for r in v] for k, v in res.items()}}
    return out


def level_loop(EU, cfg):
    """ExperienceUpdater.run: два батча подряд с одним recorder, G = 4."""
    upd = EU.ExperienceUpdater(cfg, AGENT_OBJ, LEARN_OBJ)
    rec = EU.TaskRecorder(experiment_name="bridge")
    steps = [
        {"groups": {"A": [1, 0, 1, 0], "B": [1, 1, 1, 1], "C": [0, 0, 0, 0], "D": [0, 0, 0, 1]}, "group_ops": {}},
        {"groups": {"A": [0, 1, 0, 0], "E": [1, 1, 0, 1], "F": [1, 0, 0, 0]},
         "group_ops": {
             "A": [{"operation": "UPDATE", "id": "G0", "content": "Rule A: check the arithmetic of A twice."}],
             "F": [{"operation": "DELETE", "id": "G1", "content": "Rule D: check the arithmetic of D."}],
         }},
    ]
    out = []
    for step in steps:
        LLM.rules = default_rules(step["group_ops"])
        reset()
        rolls = [sample(EU, c, i, float(r)) for c, rs in step["groups"].items() for i, r in enumerate(rs)]
        before = dict(rec.experiences or {})
        new = run(upd.run(rolls, rec, concurrency=16, given_ground_truth=True, num_experiences=1))
        out.append({"rewards": step["groups"], "before": before, "experiences": new,
                    "recorder_experiences": rec.experiences, "requests": calls()})
    return out


def main():
    if sys.argv[1:] == ["config"]:
        fake.offline()
        capture_config()
        return
    env = {**os.environ, **UTU_ENV}
    for k in ("UTU_DB_URL", "PHOENIX_ENDPOINT", "PHOENIX_PROJECT_NAME"):
        env.pop(k, None)
    res = subprocess.run([sys.executable, os.path.abspath(__file__), "config"], env=env,
                         capture_output=True, text=True, check=True)
    print("\n".join(x for x in res.stdout.splitlines() if x.startswith("wrote")))
    model_params = json.loads(res.stdout.strip().splitlines()[-1])

    fake.offline()
    EU = install_shims()
    cfg = make_config(model_params)
    upd = EU.ExperienceUpdater
    head = fake.header("youtu-agent", {
        "ExperienceUpdater.run": upd.run,
        "ExperienceUpdater._single_rollout_summary": upd._single_rollout_summary,
        "ExperienceUpdater._group_advantage": upd._group_advantage,
        "ExperienceUpdater._group_update": upd._group_update,
        "ExperienceUpdater._batch_update": upd._batch_update,
        "ExperienceUpdater._format_exp_and_ops": upd._format_exp_and_ops,
        "prompts": "utu/prompts/practice/experience.yaml",
    })
    head["note"] = ("шим utu из repro/tfgrpo_run.py:58-140; FileUtils как utu/utils/path.py:75,108; "
                    "asyncio.as_completed заменён на порядок создания; model_params из config.json "
                    f"({json.dumps(model_params)})")
    fake.write(METHOD, "prompts", head, level_prompts(EU, cfg))
    fake.write(METHOD, "parsers", head, level_parsers(EU, cfg))
    fake.write(METHOD, "memory", head, level_memory(EU, cfg))
    fake.write(METHOD, "loop", head, level_loop(EU, cfg))


if __name__ == "__main__":
    main()
