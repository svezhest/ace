"""Мостик к MCE (meta-context-engineering c4b7a7c, bridge/fixtures/mce): промпты мета-агента и базового агента,
база навыков и разбор Skill Overview, выбор итерации, evaluations.json, папки под-итераций и цикл main() на тех же
заготовках агентов, что в bridge/capture_mce.py. Задачи у нас свои (formula вместо symptom_diagnosis), поэтому
сверяется режим апстрима без интерфейсов; нормализации — только по записям DEVIATIONS.md."""
import json
import re
from types import SimpleNamespace

from upstream import deviation, fixture

from ace import fs, render
from ace.learner import swap
from ace.loop import Protocol, run
from ace.memory.mce import BASE, WORKSPACE
from ace.methods.mce import mce_fs as mce
from ace.wrap.mce import META, MISSING, evaluations
from ace.model import Reply, roles
from ace.tasks import Task
from ace.loop import best_index as best_iteration
from ace.wrap.mce import Iteration, Meta, SKILL, sub_folder

PROMPTS, PARSERS, MEMORY, LOOP = (fixture("mce", level) for level in ("prompts", "parsers", "memory", "loop"))

# навыки и evaluations.json, из которых capture_mce.py строил базу навыков (capture_prompts, capture_parsers)
SKILL_OK = "# Skill\n\n## Skill Overview\nRead train.json, group mistakes.\n\n  Add rules.\n\n## Methodology\n1. step\n"
SKILL_LAST = "## skill overview\nOnly section, no next heading.\n"
SKILL_SUB = "## Skill Overview\nText\n### Sub heading stays\nmore\n## Next\nx\n"
SKILL_NONE = "# Skill\n\nNo overview here.\n"
SKILL_EMPTY = "## Skill Overview\n\n## Methodology\nx\n"
SKILLS = {"iter1": SKILL_OK, "iter3": SKILL_LAST, "iter4": SKILL_NONE, "iter5": SKILL_EMPTY}
EVALS = {
    "iter0": {"val_accuracy": 0.9, "val_metrics": {"accuracy": 0.9}},
    "iter1": {"train_accuracy": 0.5, "val_accuracy": 0.25, "train_metrics": {"accuracy": 0.5},
              "val_metrics": {"accuracy": 0.25}, "total_rollouts": 50, "num_sub_iters": 2, "last_sub_folder": "iter1_sub1"},
    "iter3": {"train_f1": 0.123456, "val_f1": 1.0, "val_metrics": {"f1": 1.0, "accuracy": 0.0},
              "total_rollouts": 25, "num_sub_iters": 1, "last_sub_folder": "iter3_sub0"},
    "iter4": {"train_accuracy": 0.0, "val_accuracy": 0.0, "val_metrics": {"accuracy": 0.0}},
    "iter5": {"train_accuracy": 1.0, "val_accuracy": 1.0, "val_metrics": {"accuracy": 1.0}},
}

# утилит у базового агента нет (MCE2): что из промптов апстрима убрано
UTILS_TREE = """  utils/
    llm.py                                   # LLM calls (call_llm)
    embedding.py                             # Embeddings (compute_embedding_similarity)
"""
ENVIRONMENT = "## Environment\n\nUse `uv run python ...` for all Python execution.\n\n"
MENTION_UTILS = "- Mention useful utilities (`utils/llm.py`, `utils/embedding.py`)\n"


# папка навыка апстрима — из его промпта; у нас своя (MCE5)
UPSTREAM_SKILL = re.search(r"(\.\w+)/skills/learning-context/SKILL\.md", PROMPTS["base_agent_variants"]["no_signatures"]).group(1)


def skill_dir(text):
    """Путь навыка апстрима -> наш (MCE5)."""
    deviation("MCE5")
    return text.replace(UPSTREAM_SKILL + "/", SKILL.split("/", 1)[0] + "/")


def cut(text, start, end):
    """Текст без куска от start до end (end остаётся)."""
    a = text.index(start)
    return text[:a] + text[text.index(end, a):]


def without_utilities_base(text):
    deviation("MCE2")
    assert UTILS_TREE in text and ENVIRONMENT in text
    return skill_dir(cut(text.replace(UTILS_TREE, "").replace(ENVIRONMENT, ""), "## Available Utilities", "## Core Objective"))


def without_utilities_meta(text):
    deviation("MCE2")
    assert MENTION_UTILS in text
    return skill_dir(cut(text.replace(MENTION_UTILS, ""), "### Example Skill B", "## Output Requirements"))


def database(prompt):
    return prompt.split("## Skill Database (Iteration History)\n\n", 1)[1].split("\n\n## Your Task", 1)[0]

# промпты


def test_base_agent_prompt():
    """Базовый агент апстрима без интерфейсов (build_base_agent_prompt с пустыми сигнатурами)."""
    want = without_utilities_base(PROMPTS["base_agent_variants"]["no_signatures"])
    assert BASE.fill(task_instruction="Task.", iter_dir="/ws/t/iter1_sub0", iter_name="iter1_sub0") == want


def meta_fill(task, workspace, iter_name, current, evals, skills):
    return META.fill(task_instruction=task, workspace=workspace, iter_name=iter_name,
                     skill_output_path=f"{workspace}/{iter_name}/{SKILL}",
                     skill_database=render.skill_database(evals, skills, current))


def test_meta_agent_prompt_no_interfaces():
    """Мета-агент апстрима без интерфейсов на iter2 с историей iter1."""
    want = without_utilities_meta(PROMPTS["meta_agent_iter2_no_sigs"])
    assert meta_fill("Task.", "<TMP>/skilldb/t", "iter2", 2, EVALS, SKILLS) == want


def test_meta_agent_prompt_symptom():
    """Промпт мета-агента symptom_diagnosis (iter1) отличается от нашего только разделом интерфейсов (MCE1)."""
    deviation("MCE1")
    sd = PROMPTS["symptom_diagnosis"]
    upstream = without_utilities_meta(sd["meta_agent_iter1"])
    ours = meta_fill(sd["task_instruction"], "/ws/symptom", "iter1_sub0", 1, {}, {})
    no_interfaces = "## Required Interfaces\n\nNo specific interfaces defined.\n\n"
    assert cut(upstream, "## Required Interfaces", "## Your Role") == ours.replace(no_interfaces, "")


def test_skill_database():
    """_build_skill_database: пропуск итерации без записи, метрика — первый ключ val_metrics (iter3: f1), строки
    Rollouts и Files, все виды Skill Overview; iter0 и iter1 — свои строки."""
    assert render.skill_database(EVALS, SKILLS, 6) == database(PROMPTS["meta_agent_iter6"])
    assert render.skill_database(EVALS, SKILLS, 2) == database(PROMPTS["meta_agent_iter2_no_sigs"])
    assert render.skill_database({}, {}, 1) == database(PROMPTS["symptom_diagnosis"]["meta_agent_iter1"])
    assert render.skill_database({}, {}, 0) == database(PROMPTS["meta_agent_iter0"])


def test_skill_missing_feedback():
    """Просьба записать SKILL.md (mce/meta_agent.py:282, в fixtures не снята — текст из исходника), инструмент
    create вместо Write (MCE3)."""
    deviation("MCE3")
    path = f"/ws/t/iter1_sub0/{UPSTREAM_SKILL}/skills/learning-context/SKILL.md"
    upstream = (f"\n⚠️ VALIDATION ERROR\n\nYour SKILL.md file was not found at the expected location:\n{path}\n\n"
                f"Please create the SKILL.md file at this EXACT path using the Write tool.\n\nRequired:\n"
                f"1. Write to path: {path}\n2. Include ## Skill Overview section\n3. Provide complete learning methodology\n\n"
                f"Please create the SKILL.md file now.\n")
    assert MISSING.fill(expected_path=path) == upstream.replace("using the Write tool", "using the create tool")

# разборщики


def test_extract_skill_overview():
    ov = PARSERS["extract_skill_overview"]
    for key, text in dict(ok=SKILL_OK, last=SKILL_LAST, sub=SKILL_SUB, none=SKILL_NONE, empty=SKILL_EMPTY).items():
        assert render.overview(text) == ov[key], key
    assert render.overview(None) == ov["missing"]


def test_folder_names():
    """get_sub_iteration_folder_name для под-итераций: итерация = проход + 1, под-итерация = номер батча."""
    ours = [sub_folder(SimpleNamespace(epoch=it - 1, batch=sub)) for it, sub in ((1, 0), (2, 3))]
    assert ours == PARSERS["folder_names"][2:]

# выбор итерации и evaluations.json


def best_of(evals, current):
    """Наш выбор по тем же evaluations.json: итерации до текущей, у которых есть val_accuracy."""
    its = [i for i in range(current) if "val_accuracy" in evals.get(f"iter{i}", {})]
    best = best_iteration([evals[f"iter{i}"]["val_accuracy"] for i in its])
    return None if best is None else its[best]


def test_find_best_iteration():
    """_find_best_iteration: с iter2 лучшая из прошлых, строго больше, при равенстве первая; будущие итерации и
    итерации без метрики не в счёт. iter0 в evaluations.json main() не пишет (--start-iter 1 по умолчанию),
    поэтому и у нас её нет."""
    cases = {
        "iter2_only_iter1": ({"iter1": 0.4}, 2),
        "iter3_all_worse_iter0_absent": ({"iter1": 0.4, "iter2": 0.3}, 3),
        "iter3_tie_first_wins": ({"iter1": 0.5, "iter2": 0.5}, 3),
        "iter3_all_zero": ({"iter1": 0.0, "iter2": 0.0}, 3),
        "iter3_future_iter_ignored": ({"iter1": 0.1, "iter5": 0.99}, 3),
        "iter3_no_last_sub_folder": ({"iter1": 0.1, "iter2": 0.7}, 3),
        "iter4_gap_and_missing_metric": ({"iter1": None, "iter3": 0.2}, 4),
    }
    for name, (vals, current) in cases.items():
        evals = {k: ({} if v is None else {"val_accuracy": v}) for k, v in vals.items()}
        assert best_of(evals, current) == MEMORY["find_best_iteration"][name]["iteration"], name
    assert MEMORY["find_best_iteration"]["iter3_all_worse_than_iter0_in_file"]["iteration"] == 0     # только руками
    assert MEMORY["find_best_iteration"]["iter1_with_iter0"]["iteration"] == 0      # iter1 — с исходной памяти


def test_evaluations_json():
    """aggregate_iteration_results после iter1: батчи 3 и 1 с долей 1/3 и 1 -> train 0.5 (среднее с весом), val,
    число под-итераций и последняя папка. Метрика у задач одна — accuracy (S2)."""
    want = json.loads(MEMORY["aggregate_iteration_results"]["after_iter1"]["evaluations.json"])
    deviation("S2")
    want["iter1"]["train_metrics"] = {"accuracy": want["iter1"]["train_metrics"]["accuracy"]}
    h = Iteration("s", (1 + 1) / (3 + 1), 0.5, None, val_total=4, rollouts=4, folders={"iter1_sub0": {}, "iter1_sub1": {}})
    assert evaluations([h]) == want
    assert render.pretty_json(evaluations([h])) == json.dumps(want, indent=2)

# цикл: main() на заготовках агентов capture_mce.py


class Small(Task):
    """formula: val из 4 вопросов, как --val-limit 4 в эталоне."""
    def load(self, split="", size=None):
        rows = super().load(split, size)
        return rows[:4] if split == "val" else rows


def visible(deps):
    """Файлы, которые видит агент: путь от корня его папки (или workspace)."""
    return sorted(f"{name}/{path}" for name, m in deps.mounts.items() for path in m.store.files)


class Agents:
    """Заготовки агентов capture_mce.py: мета-агент пишет навык поколения k; базовый дописывает урок на каждую ошибку
    батча к прежнему контексту, на iter2 пишет контекст заново. Решатель верен, если в контексте есть урок с его
    ответом (как diagnose() эталона)."""
    name = "agents"

    def __init__(self, targets):
        self.targets, self.calls = targets, []

    def ask(self, call):
        system, user = roles(call.messages)
        deps = call.deps
        if user.startswith("# Meta-Level Agent"):
            it = int(re.search(r"iter(\d+)_sub0", user).group(1))
            self.calls.append(dict(agent="meta", iteration=it, user=user, files=visible(deps)))
            fs.create(SimpleNamespace(deps=deps), f"{WORKSPACE}/iter{it}_sub0/{SKILL}",
                      f"## Skill Overview\nSkill generation {it}: write LESSON lines for misses.\n\n## Steps\n1.\n")
            return Reply("done", "done", False, [])
        if user.startswith("# Context Engineer"):
            folder = re.search(r"\*\*Working Directory\*\*: `/workspace/(iter\d+_sub\d+)`", user).group(1)
            train = json.loads(deps.mounts["data"].store.files["train.json"])
            context = deps.mounts["context"].store
            self.calls.append(dict(agent="base", folder=folder, files=visible(deps), train=train, context=dict(context.files)))
            old = context.files.get("knowledge.md", "") if not folder.startswith("iter2") else ""
            new = [f"LESSON {r['ground_truth']}: {r['question'][:40]}" for r in train["detailed_results"] if not r["is_correct"]]
            context.write("knowledge.md", old + "".join(line + "\n" for line in new))
            return Reply("done", "done", False, [])
        target = next(t for q, t in self.targets.items() if q in user)
        text = f"FINAL ANSWER: {target if f'LESSON {target}:' in system else '0'}"
        return Reply(text, text, False, [])

    def usage(self):
        return dict(calls=len(self.calls), prompt_tokens=0, completion_tokens=0)


def upstream_files(files):
    """Файлы папки апстрима без interfaces/ (MCE1) и utils/ (MCE2)."""
    deviation("MCE1", "MCE2")
    return sorted(skill_dir(f) for f in files if not re.match(r"(iter\d+_sub\d+/)?(interfaces|utils)/", f))


def test_loop(tmp_path):
    deviation("S3")       # train у нас в одном порядке: состав батчей тот же на каждом проходе
    """main(): 3 итерации, train 6 батчами по 4, val 4 (argv эталона). Совпадают порядок агентов и папки
    под-итераций, что видит каждый агент (без interfaces/ и utils/), сводки train.json (только текущий батч),
    evaluations.json и база навыков (кроме долей верных: данные другие), с какой папки начинается итерация."""
    task = Small("formula")
    targets = {r["question"]: r["target"] for s in ("", "train", "val") for r in task.load(s)}
    model, history = Agents(targets), []

    class Spy(Meta):
        def on_pass(self, ex):
            super().on_pass(ex)
            history[:] = self.history
    learner = swap(mce, every=4, protocol=Protocol(offline=True, epochs=3))
    run(task, Spy(learner.inner, learner.author, "mce"), model, 6, str(tmp_path))
    want = [c for c in LOOP["agent_calls"] if c["iteration"] >= 1]
    got = model.calls
    assert [(c["agent"], c["iteration"] if c["agent"] == "meta" else c["folder"]) for c in got] == \
        [(c["agent"], c["iteration"] if c["agent"] == "meta" else c["iter_dir"]) for c in want]
    for g, w in zip(got, want):
        files = w["workspace"] if w["agent"] == "meta" else list(w["sees"])
        assert g["files"] == upstream_files(files), (w["agent"], w["iter_dir"])
        if w["agent"] == "base":
            summary = json.loads(w["sees"]["data/train.json"])["summary"]
            keep = ("train_total", "train_errors", "batch_idx", "cumulative_rollouts")
            assert {k: g["train"]["summary"][k] for k in keep} == {k: summary[k] for k in keep}
            assert list(g["train"]["summary"]) == list(summary)
            assert len(g["train"]["detailed_results"]) == len(json.loads(w["sees"]["data/train.json"])["detailed_results"])
    # evaluations.json и база навыков в промпте мета-агента: всё, кроме долей верных
    number = lambda s: re.sub(r"\d+\.\d+%", "<p>", s)
    for g, w in zip(got, want):
        if w["agent"] == "meta":
            assert number(database(g["user"])) == number(database(w["prompt"]))
    evals = json.loads(LOOP["workspace"]["symptom_diagnosis/meta_agent/evaluations.json"])
    ours = evaluations(history)
    assert list(ours) == list(evals)
    for it in evals:
        assert list(ours[it]) == list(evals[it])
        for k in ("train_metrics", "val_metrics", "val_total", "total_rollouts", "num_sub_iters", "last_sub_folder"):
            assert ours[it][k] == evals[it][k] if not k.endswith("metrics") else list(ours[it][k]) == list(evals[it][k]), (it, k)
    # iter2 начинается с последней папки iter1; iter3 — с лучшей по val (в эталоне тоже iter1: 0.25 против 0.0)
    base = {c["folder"]: c for c in got if c["agent"] == "base"}
    assert base["iter2_sub0"]["context"] == base_after(base, "iter1_sub1")
    best = best_iteration([h.val for h in history[:2]])
    assert base["iter3_sub0"]["context"] == base_after(base, f"iter{best + 1}_sub1")
    sees = {c["iter_dir"]: c for c in want if c["agent"] == "base"}
    assert sees["iter3_sub0"]["sees"]["context/knowledge.md"] == \
        LOOP["workspace"]["symptom_diagnosis/iter1_sub1/context/knowledge.md"]


def base_after(base, folder):
    """Контекст после базового агента под-итерации folder (как его записала заготовка)."""
    c = base[folder]
    old = c["context"].get("knowledge.md", "") if not folder.startswith("iter2") else ""
    new = [f"LESSON {r['ground_truth']}: {r['question'][:40]}" for r in c["train"]["detailed_results"] if not r["is_correct"]]
    return {"knowledge.md": old + "".join(line + "\n" for line in new)}
