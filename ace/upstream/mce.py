"""MCE апстрима (meta-context-engineering: mce/utils.py, main.py, env/base.py, prompts/): общее для памяти (базовый
агент) и меты (мета-агент) — пути и имена папок под-итераций, навык в папке, интерфейсы задачи, инструкция задачи
агентам, workspace на диске и уборка папки после агента."""
import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from .. import prompts, render
from ..tasks import variant

ROUNDS = 30                 # раундов файловых инструментов у агентов mce_fs
WORKSPACE = "/workspace"    # корень, как его видят агенты (E2B-пути апстрима)
SKILL = ".agent/skills/learning-context/SKILL.md"      # навык в папке под-итерации (MCE5)
CLAUDE_SKILL = ".claude/skills/learning-context/SKILL.md"
# mce/workspace_utils апстрима дословно: копия в utils/ под-итерации
UTILS = Path(__file__).parent.parent / "memory" / "mce_utils"
MCE = prompts.macros("mce_strings")


def task_instruction(task):
    """Инструкция задачи агентам: у бенчмарка апстрима — его get_task_instruction (mce_task_<задача>), у задач стенда
    — системный промпт и инструкция решателю (S2)."""
    if variant("mce", task) == "symptom":
        return prompts.text("mce_task_symptom")
    return f"{task.system} {task.instr}"


@dataclass(frozen=True)
class Signature:
    """InterfaceSignature: функция, которую пишет базовый агент, и её описание для промптов."""
    name: str
    inputs: tuple           # (имя, тип, описание)
    output: tuple           # (тип, описание)
    description: str

    @property
    def args(self):
        return render.signature_args(self.inputs)


SIGNATURES = {"symptom": (Signature("get_context", inputs=(("symptoms", "str", MCE.symptoms()),),
                                    output=("str", MCE.context()), description=MCE.get_context()),)}


def signatures(task):
    """Интерфейсы задачи (get_interface_signatures); у задач стенда их нет (MCE1)."""
    return SIGNATURES.get(variant("mce", task), ())


def folder_name(iteration, sub=None):
    """get_sub_iteration_folder_name."""
    return f"iter{iteration}" if sub is None else f"iter{iteration}_sub{sub}"


def sub_folder(ex):
    """Папка текущей под-итерации: итерация = проход, под-итерация = батч."""
    return folder_name(ex.epoch + 1, ex.batch)


def ignore_pycache(directory, contents):
    return ["__pycache__"] if "__pycache__" in contents else []


class Workspace:
    """workspace апстрима на диске: root/workspace/<name>; root — как корень репозитория апстрима (в нём окружение
    агентов, model/claude.py). Функции mce/utils.py."""
    def __init__(self, root, name):
        self.root = Path(root)
        self.base = self.root / "workspace" / name

    def start(self, task):
        """Новый workspace и setup_meta_agent_reference: meta_agent/train.jsonl — файл train целиком. Утилиты
        лежат в корне, как в репозитории апстрима (mce/workspace_utils): оттуда их копирует setup, их же находит
        агент, если ищет вне workspace."""
        if self.base.exists():
            shutil.rmtree(self.base)
        utils = self.root / "mce" / "workspace_utils"
        if not utils.exists():
            shutil.copytree(UTILS, utils, ignore=ignore_pycache)
        self.base.mkdir(parents=True)
        ref = self.base / "meta_agent"
        ref.mkdir()
        (ref / "skills").mkdir()
        (ref / "train.jsonl").write_text(task.file("train").read_text())

    def create(self, iteration, sub):
        """create_iteration_workspace: папка под-итерации и .claude/skills/learning-context."""
        folder = self.base / folder_name(iteration, sub)
        if folder.exists():
            raise FileExistsError(f"Iteration folder already exists at {folder}")
        folder.mkdir(parents=True)
        (folder / CLAUDE_SKILL).parent.mkdir(parents=True)
        return folder

    def setup(self, folder, source):
        """setup_base_agent_workspace: context/ и interfaces/ из source (нет — пустые), utils/, data/."""
        for part in ("context", "interfaces"):
            src, dst = source / part, folder / part
            if src.exists() and not dst.exists():
                shutil.copytree(src, dst, ignore=ignore_pycache)
            elif not dst.exists():
                dst.mkdir(parents=True)
        if not (folder / "utils").exists():
            shutil.copytree(self.root / "mce" / "workspace_utils", folder / "utils", ignore=ignore_pycache)
        (folder / "data").mkdir(exist_ok=True)

    def copy_skills(self, source, folder):
        """copy_skills_to_sub_iteration."""
        shutil.copytree(source / ".claude" / "skills", folder / ".claude" / "skills", ignore=ignore_pycache,
                        dirs_exist_ok=True)

    def aggregate(self, iteration, subs, val_metrics, val_total, last):
        """aggregate_iteration_results: итерация в meta_agent/evaluations.json (train — метрики батчей, среднее с
        весом размера), навык последней под-итерации — в meta_agent/skills/iter{k}/SKILL.md. subs — батчи:
        {"batch_size", "metric" (accuracy), "metrics"}. -> train итерации."""
        total = sum(s["batch_size"] for s in subs)
        train = sum(s["metric"] * s["batch_size"] for s in subs) / total if total > 0 else 0.0
        train_metrics = {}
        if subs:
            for name in subs[0]["metrics"]:
                weighted = sum(s["metrics"].get(name, 0.0) * s["batch_size"] for s in subs)
                train_metrics[name] = weighted / total if total > 0 else 0.0
        evaluations = self.evaluations()
        evaluations[f"iter{iteration}"] = {"train_accuracy": train, "train_metrics": train_metrics,
                                           "val_accuracy": val_metrics.get("accuracy", 0.0), "val_metrics": val_metrics,
                                           "val_total": val_total, "total_rollouts": total, "num_sub_iters": len(subs),
                                           "last_sub_folder": last.name}
        (self.base / "meta_agent" / "evaluations.json").write_text(render.pretty_json(evaluations))
        skill = last / CLAUDE_SKILL
        if iteration >= 1 and skill.exists():
            target = self.base / "meta_agent" / "skills" / f"iter{iteration}"
            target.mkdir(parents=True, exist_ok=True)
            shutil.copy2(skill, target / "SKILL.md")
        return train

    def evaluations(self):
        """meta_agent/evaluations.json; нет файла — {}."""
        file = self.base / "meta_agent" / "evaluations.json"
        return json.loads(file.read_text()) if file.exists() else {}

    def skills(self):
        """Архив навыков meta_agent/skills/iter*/SKILL.md."""
        return {p.parent.name: p.read_text() for p in (self.base / "meta_agent" / "skills").glob("iter*/SKILL.md")}


def cleanup(folder):
    """cleanup_irrelevant_files: в корне под-итерации остаётся только своё (скрытое не трогается); у апстрима вид
    агента выбирает только строку лога."""
    keep = {"data", "utils", "__pycache__", ".claude", "context", "interfaces"}
    for item in folder.iterdir():
        if item.name in keep or item.name.startswith("."):
            continue
        try:
            if item.is_file():
                item.unlink()
            elif item.is_dir():
                shutil.rmtree(item)
        except Exception:
            pass
