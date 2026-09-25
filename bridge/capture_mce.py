"""Эталоны MCE (meta-context-engineering c4b7a7c): промпты, разборщики, итерации, цикл main().

Запуск из корня стенда: /Users/user/Projects/upstreams/.venvs/mce/bin/python bridge/capture_mce.py
Агентов Claude SDK не запускаем: run_meta_agent и run_base_agent заменены заготовками, которые
строят промпт настоящими билдерами и пишут файлы, как агент; модель оценки — фейк.
"""
import asyncio
import json
import os
import random
import sys
from pathlib import Path

sys.argv[0] = os.path.abspath(sys.argv[0])
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fake  # noqa: E402

REPO = os.path.join(fake.UPSTREAMS, "meta-context-engineering")
TMP = fake.offline()  # до импорта апстрима: load_dotenv(override=True) ищет .env от cwd
for k in ("OPENROUTER_API_KEY", "OPENROUTER_API_BASE", "OPENAI_API_BASE"):
    os.environ.pop(k, None)
sys.path.insert(0, REPO)

import mce.main as mm  # noqa: E402
from env.base import InterfaceSignature, Sample  # noqa: E402
from env.registry import EnvironmentRegistry  # noqa: E402
from mce import utils as mu  # noqa: E402
from mce.eval import batch_evaluate  # noqa: E402
from mce.llm_client import LLMClient  # noqa: E402
from mce.meta_agent import _verify_meta_agent_outputs  # noqa: E402
from mce.prompts import base_agent as pb, meta_agent as pm  # noqa: E402
from mce.validation import ValidationResult, format_validation_feedback, validate_interfaces  # noqa: E402

ENVS = ["symptom_diagnosis", "symptom_diagnosis_twostep", "symptom_diagnosis_agent"]
LOG = mu.logging.getLogger("bridge")


def norm(x):
    """Пути tmp заменяем метками, чтобы эталон не зависел от запуска."""
    if isinstance(x, str):
        return x.replace(os.path.realpath(TMP), "<TMP>").replace(TMP, "<TMP>").replace(REPO, "<REPO>")
    if isinstance(x, dict):
        return {k: norm(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [norm(v) for v in x]
    return x


def snapshot(root):
    """Файлы каталога: путь -> текст (utils/ — только имена, это копия workspace_utils)."""
    out = {}
    for p in sorted(Path(root).rglob("*")):
        if p.is_dir() or "__pycache__" in p.parts:
            continue
        rel = str(p.relative_to(root))
        if "/utils/" in f"/{rel}" or rel.endswith("train.jsonl"):
            out[rel] = f"<{p.stat().st_size} bytes>"
        else:
            out[rel] = norm(p.read_text(encoding="utf-8"))
    return out


def ws(name):
    d = Path(TMP) / name
    d.mkdir(parents=True)
    return d


def write_evals(base, evals, skills=None):
    (base / "meta_agent").mkdir(parents=True, exist_ok=True)
    (base / "meta_agent" / "evaluations.json").write_text(json.dumps(evals))
    for it, text in (skills or {}).items():
        d = base / "meta_agent" / "skills" / it
        d.mkdir(parents=True, exist_ok=True)
        (d / "SKILL.md").write_text(text)


SIG = InterfaceSignature(
    name="get_context",
    inputs=[("symptoms", "str", "Patient symptom description"), ("k", "int", "How many snippets")],
    output=("str", "Relevant context"),
    description="Return context for the question.",
)
SKILL_OK = "# Skill\n\n## Skill Overview\nRead train.json, group mistakes.\n\n  Add rules.\n\n## Methodology\n1. step\n"
SKILL_LAST = "## skill overview\nOnly section, no next heading.\n"
SKILL_SUB = "## Skill Overview\nText\n### Sub heading stays\nmore\n## Next\nx\n"
SKILL_NONE = "# Skill\n\nNo overview here.\n"
SKILL_EMPTY = "## Skill Overview\n\n## Methodology\nx\n"


# --- 1. промпты ----------------------------------------------------------------------------------

def capture_prompts():
    data = {}
    for name in ENVS:
        env = EnvironmentRegistry.get(name)
        sigs = env.get_interface_signatures()
        data[name] = {
            "task_instruction": env.get_task_instruction(),
            "primary_metric": env.get_primary_metric_name(),
            "signatures": [{"to_prompt": s.to_prompt(), "to_stub": s.to_stub()} for s in sigs],
            "base_agent": pb.build_base_agent_prompt(
                env.get_task_instruction(), sigs, "/ws/symptom/iter2_sub1", "/ws/symptom"),
            "meta_agent_iter1": pm.build_meta_agent_prompt(
                env.get_task_instruction(), sigs, "/ws/symptom/iter1_sub0", "/ws/symptom"),
        }
    env = EnvironmentRegistry.get("symptom_diagnosis")
    data["symptom_diagnosis"]["diagnosis_prompt"] = {
        "with_context": env._build_diagnosis_prompt("itching, rash", "- fungal infection: itching"),
        "no_context": env._build_diagnosis_prompt("itching, rash", ""),
    }
    two = EnvironmentRegistry.get("symptom_diagnosis_twostep")
    data["symptom_diagnosis_twostep"]["narrowing_prompt"] = two._build_narrowing_prompt("cough", "ctx")
    data["symptom_diagnosis_twostep"]["final_prompt"] = two._build_diagnosis_prompt("cough", "flu, cold", "")
    agent = EnvironmentRegistry.get("symptom_diagnosis_agent")
    ctx = ws("agent_ctx") / "context"
    ctx.mkdir()
    data["symptom_diagnosis_agent"]["agent_prompt"] = {
        "with_dir": norm(agent._build_agent_prompt("fever", ctx)),
        "no_dir": agent._build_agent_prompt("fever", None),
    }

    data["base_agent_variants"] = {
        "two_inputs_initial_prompt": pb.build_base_agent_prompt(
            "Task.", [SIG], "/ws/t/iter1_sub0", None, initial_prompt="Be brief."),
        "no_signatures": pb.build_base_agent_prompt("Task.", [], "/ws/t/iter1_sub0", "/ws/t"),
    }

    # база навыков: iter2 без оценки, SKILL.md разных видов, метрика не accuracy
    base = ws("skilldb/t")
    write_evals(base, {
        "iter0": {"val_accuracy": 0.9, "val_metrics": {"accuracy": 0.9}},
        "iter1": {"train_accuracy": 0.5, "val_accuracy": 0.25, "train_metrics": {"accuracy": 0.5},
                  "val_metrics": {"accuracy": 0.25}, "total_rollouts": 50, "num_sub_iters": 2,
                  "last_sub_folder": "iter1_sub1"},
        "iter3": {"train_f1": 0.123456, "val_f1": 1.0, "val_metrics": {"f1": 1.0, "accuracy": 0.0},
                  "total_rollouts": 25, "num_sub_iters": 1, "last_sub_folder": "iter3_sub0"},
        "iter4": {"train_accuracy": 0.0, "val_accuracy": 0.0, "val_metrics": {"accuracy": 0.0}},
        "iter5": {"train_accuracy": 1.0, "val_accuracy": 1.0, "val_metrics": {"accuracy": 1.0}},
    }, {"iter1": SKILL_OK, "iter3": SKILL_LAST, "iter4": SKILL_NONE, "iter5": SKILL_EMPTY})
    data["meta_agent_iter6"] = norm(pm.build_meta_agent_prompt(
        "Task.", [SIG], str(base / "iter6_sub0"), str(base)))
    data["meta_agent_iter2_no_sigs"] = norm(pm.build_meta_agent_prompt(
        "Task.", [], str(base / "iter2"), str(base)))
    data["meta_agent_iter0"] = pm.build_meta_agent_prompt("Task.", [SIG], "/ws/t/iter0", "/ws/t")

    data["validation_feedback"] = {
        "failed": format_validation_feedback(ValidationResult(False, ["missing interfaces/get_context.py",
                                                                      "param mismatch"])),
        "passed": format_validation_feedback(ValidationResult(True, [], {"get_context": len})),
    }
    return data


# --- 2. разборщики -------------------------------------------------------------------------------

RESPONSES = [
    "[DIAGNOSIS]Fungal Infection[/DIAGNOSIS]",
    "[diagnosis] common cold. [/diagnosis]",
    "[DIAGNOSIS]allergy[/DIAGNOSIS] then [DIAGNOSIS]malaria[/DIAGNOSIS]",
    "[DIAGNOSIS]no close tag",
    "Final diagnosis: Typhoid\nmore text",
    "Conclusion：dengue",
    "I think\n\nit is  Jaundice!\n\n",
    "",
    "1. malaria\n2. dengue, typhoid\n3. flu",
    "[CANDIDATES]flu, cold ,  malaria[/CANDIDATES]",
]


def capture_parsers():
    out = {}
    for name in ENVS:
        env = EnvironmentRegistry.get(name)
        rows = []
        for r in RESPONSES:
            row = {"input": r, "diagnosis": fake.call(env._extract_diagnosis, r)}
            row["normalized"] = fake.call(env._normalize, row["diagnosis"].get("ok", ""))
            if hasattr(env, "_extract_candidates"):
                row["candidates"] = fake.call(env._extract_candidates, r)
            rows.append(row)
        item = {
            "sample": {"id": 3, "question": "q", "ground_truth": "flu"},
            "llm_output": {"final_answer": "flu"},
            "evaluation": {"metrics": {"accuracy": 1.0}, "trajectory": [
                {"step": "get_context", "output": "ctx"},
                {"step": "llm_narrowing", "candidates": ["flu", "cold"]},
                {"step": "llm_inference", "diagnosis": ""},
                {"step": "llm_diagnosis", "diagnosis": "flu"},
                {"step": "evaluate", "prediction": "flu"},
            ]},
        }
        out[name] = {"responses": rows, "format_result_for_training": fake.call(env.format_result_for_training, item),
                     "format_partial_metric": fake.call(env.format_result_for_training,
                                                        {**item, "evaluation": {"metrics": {"accuracy": 0.99}}})}

    d = ws("overview")
    ov = {}
    for key, text in {"ok": SKILL_OK, "last": SKILL_LAST, "sub": SKILL_SUB, "none": SKILL_NONE,
                      "empty": SKILL_EMPTY}.items():
        (d / f"{key}.md").write_text(text)
        ov[key] = pm._extract_skill_overview(d / f"{key}.md")
    ov["missing"] = pm._extract_skill_overview(d / "missing.md")
    out["extract_skill_overview"] = ov

    out["compute_avg_metrics"] = mu.compute_avg_metrics([
        {"evaluation": {"metrics": {"accuracy": 1.0, "f1": 0.5, "note": "x"}}},
        {"evaluation": {"metrics": {"accuracy": 0.0}}},
        {"evaluation": {}},
        {"evaluation": {"metrics": {"note": "y", "f1": 1}}},
    ])
    out["folder_names"] = [mu.get_sub_iteration_folder_name(i, s) for i, s in [(0, None), (1, None), (1, 0), (2, 3)]]
    return out


# --- 3. итерации и workspace ---------------------------------------------------------------------

class Env:
    def __init__(self, metric="accuracy"):
        self.metric = metric

    def get_primary_metric_name(self):
        return self.metric


def capture_memory():
    env = Env()
    cases = {}

    def best(label, evals, current, iter0=True, metric="accuracy"):
        base = ws(f"best/{label}")
        if iter0:
            (base / "iter0").mkdir()
        if evals is not None:
            write_evals(base, evals)
        cases[label] = mu._find_best_iteration(base, current, Env(metric))

    v = lambda x, sub=None: {"val_accuracy": x, **({"last_sub_folder": sub} if sub else {})}  # noqa: E731
    best("iter0_current", {}, 0)
    best("iter1_with_iter0", {}, 1)
    best("iter1_no_iter0", {}, 1, iter0=False)
    best("iter2_no_file", None, 2)
    best("iter2_only_iter1", {"iter1": v(0.4, "iter1_sub1")}, 2)
    # iter0 в evaluations.json main() никогда не пишет; здесь кладём руками, как если бы писал
    best("iter3_all_worse_than_iter0_in_file", {"iter0": v(0.9), "iter1": v(0.4, "iter1_sub1"),
                                                "iter2": v(0.3, "iter2_sub1")}, 3)
    best("iter3_all_worse_iter0_absent", {"iter1": v(0.4, "iter1_sub1"), "iter2": v(0.3, "iter2_sub1")}, 3)
    best("iter3_tie_first_wins", {"iter1": v(0.5, "iter1_sub1"), "iter2": v(0.5, "iter2_sub0")}, 3)
    best("iter4_gap_and_missing_metric", {"iter1": {"last_sub_folder": "iter1_sub0"},
                                          "iter3": v(0.2, "iter3_sub1")}, 4)
    best("iter3_no_last_sub_folder", {"iter1": v(0.1), "iter2": v(0.7)}, 3)
    best("iter3_all_zero", {"iter1": v(0.0, "iter1_sub0"), "iter2": v(0.0, "iter2_sub0")}, 3)
    best("iter3_future_iter_ignored", {"iter1": v(0.1, "iter1_sub0"), "iter5": v(0.99, "iter5_sub0")}, 3)
    best("iter3_other_metric", {"iter1": {"val_f1": 0.2}, "iter2": {"val_accuracy": 0.9, "val_f1": 0.1}}, 3,
         metric="f1")

    # aggregate_iteration_results: взвешенное среднее по батчам, evaluations.json, копия SKILL.md
    base = ws("agg/t")
    for sub in ("iter1_sub1", "iter2_sub0"):
        d = base / sub / ".claude" / "skills" / "learning-context"
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(f"## Skill Overview\nskill of {sub}\n")
    subs1 = [
        {"sub_iter": 0, "batch_size": 3, "batch_train_primary_metric": 1 / 3,
         "batch_train_metrics": {"accuracy": 1 / 3, "f1": 0.5}},
        {"sub_iter": 1, "batch_size": 1, "batch_train_primary_metric": 1.0,
         "batch_train_metrics": {"accuracy": 1.0}},
    ]
    mu.aggregate_iteration_results(base, 1, subs1, 0.5, {"accuracy": 0.5}, 4, 4, 2, "iter1_sub1", 3, env, LOG)
    after1 = snapshot(base / "meta_agent")
    mu.aggregate_iteration_results(base, 2, [], 0.25, {"accuracy": 0.25, "f1": 0.1}, 4, 0, 1, "iter2_sub0",
                                   3, env, LOG)
    mu.aggregate_iteration_results(base, 1, subs1[:1], 0.75, {"accuracy": 0.75}, 4, 3, 1, "iter9_sub0",
                                   3, env, LOG)  # повтор iter1 перезаписывает запись, SKILL.md нет
    agg = {"after_iter1": after1, "after_iter2_and_rewrite_iter1": snapshot(base / "meta_agent")}

    # setup_base_agent_workspace: откуда копируется context/ и interfaces/
    base = ws("setup/workspace/t")
    for folder, text in [("iter0", "seed"), ("iter1_sub1", "iter1 best"), ("iter2_sub0", "iter2 worse")]:
        for part in ("context", "interfaces"):
            (base / folder / part).mkdir(parents=True)
            (base / folder / part / "f.txt").write_text(f"{part} from {text}")
        (base / folder / "data").mkdir()
        (base / folder / "data" / "train.json").write_text(f"train of {folder}")
    write_evals(base, {"iter1": v(0.6, "iter1_sub1"), "iter2": v(0.2, "iter2_sub0")})
    setup = {}
    for label, it, src in [("iter1", 1, None), ("iter3_best", 3, None), ("iter3_sub1_from_prev", 3, "iter2_sub0")]:
        folder = base / f"{label}_target"
        folder.mkdir()
        mu.setup_base_agent_workspace(base, folder, it, env, LOG, base / src if src else None)
        setup[label] = snapshot(folder)
    try:
        mu.setup_base_agent_workspace(ws("setup2/t"), ws("setup2/t/iter2_sub0"), 2, env, LOG)
    except Exception as e:
        setup["iter2_no_evals"] = f"{type(e).__name__}: {norm(str(e))}"

    # cleanup_irrelevant_files
    cl = {}
    for kind in ("meta", "base"):
        d = ws(f"cleanup/{kind}")
        for p in ("data/train.json", "utils/llm.py", ".claude/skills/x/SKILL.md", "context/a.md",
                  "interfaces/__init__.py", "notes.md", "scratch/tmp.py", ".hidden", "retrieve_context.py"):
            (d / p).parent.mkdir(parents=True, exist_ok=True)
            (d / p).write_text("x")
        mu.cleanup_irrelevant_files(d, kind, LOG)
        cl[kind] = sorted(snapshot(d))

    return {"find_best_iteration": cases, "aggregate_iteration_results": agg,
            "setup_base_agent_workspace": setup, "cleanup_irrelevant_files": cl,
            "create_iteration_workspace": {
                "iter0": sorted(snapshot(mu.create_iteration_workspace(ws("ciw"), 0)) or ["<empty>"]),
                "iter1_sub0_dirs": sorted(str(p.relative_to(Path(TMP) / "ciw")) for p in
                                          mu.create_iteration_workspace(Path(TMP) / "ciw", 1, 0).rglob("*"))}}


# --- 4. цикл main() с заготовками агентов ---------------------------------------------------------

SYMPTOMS = {}  # вопрос -> верный диагноз, для ответов фейка


def diagnose(text):
    """Фейк отвечает верно, если болезнь из подсказки в контексте совпала с симптомами; иначе common cold."""
    line = next((ln for ln in text.splitlines() if ln.startswith("Patient symptoms: ")), "")
    truth = SYMPTOMS.get(line[len("Patient symptoms: "):], "")
    if truth and f"LESSON {truth}:" in text:
        return f"Reasoning.\n[DIAGNOSIS]{truth.title()}[/DIAGNOSIS]"
    return "Reasoning.\n[DIAGNOSIS]common cold[/DIAGNOSIS]"


LLM = fake.FakeLLM([("You are a medical diagnostician.", diagnose)])
AGENT_CALLS = []

INIT_PY = "from .get_context import get_context\n\n__all__ = ['get_context']\n"
GET_CONTEXT = '''from pathlib import Path


def get_context(symptoms: str) -> str:
    path = Path(__file__).parent.parent / "context" / "knowledge.md"
    return path.read_text() if path.exists() else ""
'''


async def stub_meta(iter_dir, task_instruction, interface_signatures, iteration, workspace_base=None,
                    run_dir=None, e2b_sandbox_manager=None):
    prompt = pm.build_meta_agent_prompt(task_instruction, interface_signatures, str(iter_dir), str(workspace_base))
    AGENT_CALLS.append({"agent": "meta", "iter_dir": iter_dir.name, "iteration": iteration,
                        "prompt": norm(prompt), "workspace": sorted(snapshot(workspace_base))})
    skill = iter_dir / ".claude" / "skills" / "learning-context" / "SKILL.md"
    skill.write_text(f"## Skill Overview\nSkill generation {iteration}: write LESSON lines for misses.\n\n## Steps\n1.\n")
    (iter_dir / "meta_scratch.txt").write_text("to be cleaned")
    res = _verify_meta_agent_outputs(iter_dir, LOG)
    mu.cleanup_irrelevant_files(iter_dir, "meta", LOG)
    return res


async def stub_base(iter_dir, task_instruction, interface_signatures, workspace_base=None, log_dir="logs",
                    run_dir=None, iteration=None, e2b_sandbox_manager=None, initial_prompt=None,
                    max_validation_attempts=3):
    prompt = pb.build_base_agent_prompt(task_instruction, interface_signatures, str(iter_dir),
                                        str(workspace_base), initial_prompt)
    train = json.loads((iter_dir / "data" / "train.json").read_text())
    AGENT_CALLS.append({"agent": "base", "iter_dir": iter_dir.name, "iteration": iteration,
                        "prompt": norm(prompt), "sees": snapshot(iter_dir)})
    # урок на каждую ошибку батча дописывается к прежнему контексту; на iter2 контекст пишется заново,
    # чтобы iter2 вышла хуже и iter3 взяла лучшую прежнюю итерацию
    know = iter_dir / "context" / "knowledge.md"
    old = know.read_text() if know.exists() and iteration != 2 else ""
    new = [f"LESSON {r['ground_truth']}: {r['symptoms'][:40]}" for r in train["detailed_results"]
           if not r["is_correct"]]
    know.write_text(old + "".join(line + "\n" for line in new))
    (iter_dir / "interfaces" / "__init__.py").write_text(INIT_PY)
    (iter_dir / "interfaces" / "get_context.py").write_text(GET_CONTEXT)
    (iter_dir / "analysis.py").write_text("to be cleaned")
    result = validate_interfaces(iter_dir, interface_signatures)
    mu.cleanup_irrelevant_files(iter_dir, "base", LOG)
    return {"success": result.success, "errors": result.errors, "validation_attempts": 1}


class FakeClient(LLMClient):
    def __init__(self, model, **kw):
        super().__init__(model=model, **kw)
        self.client = fake.FakeOpenAI(LLM, asynchronous=True)


def capture_loop():
    # workspace как в scripts/train_symptom_diagnosis.sh: <root>/workspace/<env>, <root>/mce/workspace_utils
    root = ws("loop")
    os.symlink(os.path.join(REPO, "mce"), root / "mce")
    data = root / "data"
    data.mkdir()
    src = os.path.join(REPO, "env", "symptom_diagnosis", "data")
    for split, n in (("train", 12), ("val", 4)):
        with open(os.path.join(src, f"{split}.jsonl"), encoding="utf-8") as f:
            rows = [json.loads(line) for line in f][:n]
        with open(data / f"{split}.jsonl", "w", encoding="utf-8") as f:
            f.writelines(json.dumps(r) + "\n" for r in rows)
        SYMPTOMS.update({r["question"]: r["answer"] for r in rows})
    os.chdir(root)

    results = []
    orig = mm.run_iteration

    async def recorded(**kw):
        r = await orig(**kw)
        results.append(r)
        return r

    mm.run_meta_agent, mm.run_base_agent, mm.LLMClient, mm.run_iteration = stub_meta, stub_base, FakeClient, recorded
    sys.argv = ["mce.main", "--workspace", "workspace/symptom_diagnosis", "--env", "symptom_diagnosis",
                "--train-data", "data/train.jsonl", "--val-data", "data/val.jsonl", "--model", "fake-model",
                "--iterations", "3", "--train-limit", "6", "--val-limit", "4", "--train-batch-size", "4",
                "--log-dir", "logs"]
    random.seed(0)
    asyncio.run(mm.main())

    # отдельно iter0 (main по умолчанию начинает с iter1): только валидация, в evaluations.json не пишется
    sys.argv[sys.argv.index("--iterations") + 1] = "1"
    sys.argv += ["--start-iter", "0", "--workspace", "workspace/iter0_only"]
    asyncio.run(mm.main())

    wsd = root / "workspace"
    return {
        "argv": sys.argv[1:],
        "iteration_results": norm(results),
        "agent_calls": AGENT_CALLS,
        "llm_calls": [{k: norm(c[k]) for k in ("messages", "model", "temperature", "response", "matched")}
                      for c in LLM.calls],
        "workspace": snapshot(wsd),
    }


def capture_batch_evaluate():
    """batch_evaluate напрямую с llm=фейк: ошибки интерфейса и модели как данные."""
    llm = FakeClient("fake-model")
    samples = [Sample(id=i, question=q, ground_truth=a) for i, (q, a) in enumerate(list(SYMPTOMS.items())[:2])]
    samples.append(Sample(id=9, question="unknown symptoms", ground_truth="  Malaria. "))

    def broken(symptoms):
        raise RuntimeError("boom")

    out = {}
    for label, ifaces in [("no_interfaces", {}), ("broken_interface", {"get_context": broken}),
                          ("context", {"get_context": lambda s: "LESSON malaria: x"})]:
        out[label] = asyncio.run(batch_evaluate(ifaces, samples, "symptom_diagnosis", llm=llm))
    return out


def main():
    funcs = {
        "build_meta_agent_prompt": pm.build_meta_agent_prompt,
        "build_base_agent_prompt": pb.build_base_agent_prompt,
        "_find_best_iteration": mu._find_best_iteration,
        "aggregate_iteration_results": mu.aggregate_iteration_results,
        "setup_base_agent_workspace": mu.setup_base_agent_workspace,
        "run_iteration": mm.run_iteration,
        "main": mm.main,
        "batch_evaluate": batch_evaluate,
    }
    head = fake.header("meta-context-engineering", funcs)
    fake.write("mce", "prompts", head, capture_prompts())
    fake.write("mce", "parsers", head, capture_parsers())
    fake.write("mce", "memory", head, capture_memory())
    loop = capture_loop()
    loop["batch_evaluate"] = capture_batch_evaluate()
    fake.write("mce", "loop", head, loop)


if __name__ == "__main__":
    main()
