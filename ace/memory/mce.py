"""Память базового агента MCE (meta-context-engineering: mce/base_agent.py, prompts/; промпт mce_base.j2 —
апстрим без интерфейсов и утилит, DEVIATIONS MCE1, MCE2): файлы context/ (мир документов). На батче
(под-итерации) агент по навыку правит их файловыми инструментами, до 30 раундов; в папке под-итерации
iter{k}_sub{j} — навык (.agent/, только чтение), context/ и data/train.json с итогами только текущего батча."""
import ast
import importlib.util
import json
import shutil
import sys
from dataclasses import dataclass
from functools import partial
from pathlib import Path

from .. import fs, prompts, render
from ..model import Call, messages, params
from ..tasks import variant
from . import Files, Record

BASE = prompts.load("mce_base")
ROUNDS = 30
WORKSPACE = "/workspace"    # корень, как его видят агенты (E2B-пути апстрима)
SKILL = ".agent/skills/learning-context/SKILL.md"      # навык в папке под-итерации (MCE5)


def train_json(ex, groups, ids, field="question"):
    """data/train.json под-итерации (format_result_for_training): сводка батча и итоги его вопросов с id ids."""
    eps = [g.episodes[g.chosen] for g in groups]
    acc = sum(bool(e.ok) for e in eps) / len(eps) if eps else 0.0
    summary = dict(train_accuracy=acc, train_metrics=dict(accuracy=acc) if eps else {}, train_total=len(eps),
                   train_errors=0, batch_idx=ex.batch, cumulative_rollouts=ex.i + 1)
    results = [{"id": id, field: g.question, "ground_truth": g.target, "llm_prediction": e.answer, "is_correct": bool(e.ok)}
               for id, g, e in zip(ids, groups, eps)]
    return render.train_json(summary, results)


def sub_folder(ex):
    """Папка под-итерации (get_sub_iteration_folder_name): итерация = проход, под-итерация = батч."""
    return f"iter{ex.epoch + 1}_sub{ex.batch}"


class Context(Files):
    """Файлы context/ базового агента; train — data/train.json последнего батча."""
    def __init__(self, rounds=ROUNDS):
        super().__init__("context")
        self.rounds, self.train = rounds, ""

    def learn(self, ex, extractions):
        groups = [x.group for x in extractions]
        # id — место вопроса в проходе (порядок train у нас один и тот же), вопрос — поле question
        self.train = train_json(ex, groups, range(ex.i + 1 - len(groups), ex.i + 1))
        name = sub_folder(ex)
        mounts = {"context": fs.Mount(self), "data": fs.Mount(Files.of({"train.json": self.train}), "ro")}
        if ex.skill:
            top, rest = SKILL.split("/", 1)
            mounts = {top: fs.Mount(Files.of({rest: ex.skill}), "ro"), **mounts}
        prompt = BASE.fill(task_instruction=render.task_instruction(ex.task), iter_dir=f"{WORKSPACE}/{name}", iter_name=name)
        ex.model.ask(Call(messages(prompt), params(), tools=fs.TOOLS, deps=fs.FS(mounts, root=f"{WORKSPACE}/{name}"),
                          rounds=self.rounds))

    def folder(self):
        """Папка под-итерации для мета-агента: context/ и data/train.json."""
        out = {f"context/{p}": t for p, t in self.files.items()}
        return {**out, "data/train.json": self.train} if self.train else out


# MCE апстрима на Claude Agent SDK (mce/utils.py, base_agent.py, validation.py, env/base.py): workspace на диске,
# базовый агент — Claude SDK (model/claude.py) с интерфейсами задачи (get_context у symptom), навык в .claude/.

CLAUDE_SKILL = ".claude/skills/learning-context/SKILL.md"
BASE_TOOLS = ["Skill", "Read", "Write", "Edit", "Bash", "Glob", "Grep", "Task", "TaskOutput", "ExitPlanMode", "TodoWrite",
              "KillShell", "EnterPlanMode"]
VALIDATION_TRIES = 3        # max_validation_attempts run_base_agent: ответов, пока проверка не прошла
UTILS = Path(__file__).parent / "mce_utils"     # mce/workspace_utils апстрима дословно: копия в utils/ под-итерации
CLAUDE_BASE, INTERFACES = prompts.load("mce_claude_base"), prompts.load("mce_claude_interfaces")
INVALID = prompts.load("mce_claude_invalid")
MCE = prompts.macros("mce_strings")


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
        file = self.base / "meta_agent" / "evaluations.json"
        evaluations = json.loads(file.read_text()) if file.exists() else {}
        evaluations[f"iter{iteration}"] = {"train_accuracy": train, "train_metrics": train_metrics,
                                           "val_accuracy": val_metrics.get("accuracy", 0.0), "val_metrics": val_metrics,
                                           "val_total": val_total, "total_rollouts": total, "num_sub_iters": len(subs),
                                           "last_sub_folder": last.name}
        with open(file, "w") as f:
            json.dump(evaluations, f, indent=2)
        skill = last / CLAUDE_SKILL
        if iteration >= 1 and skill.exists():
            target = self.base / "meta_agent" / "skills" / f"iter{iteration}"
            target.mkdir(parents=True, exist_ok=True)
            shutil.copy2(skill, target / "SKILL.md")
        return train

    def evaluations(self):
        file = self.base / "meta_agent" / "evaluations.json"
        return json.loads(file.read_text()) if file.exists() else {}

    def skills(self):
        """Архив навыков meta_agent/skills/iter*/SKILL.md."""
        return {p.parent.name: p.read_text() for p in (self.base / "meta_agent" / "skills").glob("iter*/SKILL.md")}


def cleanup(folder, agent):
    """cleanup_irrelevant_files: в корне под-итерации остаётся только своё (скрытое не трогается)."""
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


async def base_permission(tool_name, input_data, context, iter_dir):
    """base_agent_permission_handler апстрима дословно. Отвечает dict, а SDK ждёт PermissionResult — вызов
    падает TypeError, и CLI получает ошибку; зовётся он только для инструментов вне allowed_tools (остальные
    разрешены заранее), так что пути он на деле не ограничивает. Так у апстрима — так и здесь."""
    if tool_name not in BASE_TOOLS:
        return {"behavior": "deny", "message": MCE.base_tool_denied(tool=tool_name, allowed=", ".join(BASE_TOOLS)),
                "interrupt": False}
    iter_dir = iter_dir.resolve()
    if tool_name in ["Read", "Write", "Edit", "Glob", "Grep"]:
        file_path = input_data.get("file_path") or input_data.get("path")
        if file_path:
            if not Path(file_path).is_absolute():
                resolved = (iter_dir / file_path).resolve()
            else:
                resolved = Path(file_path).resolve()
            try:
                resolved.relative_to(iter_dir)
            except ValueError:
                return {"behavior": "deny", "message": MCE.base_outside(folder=iter_dir), "interrupt": True}
            if tool_name in ["Write", "Edit"]:
                try:
                    resolved.relative_to((iter_dir / "utils").resolve())
                    return {"behavior": "deny", "message": MCE.base_utils(), "interrupt": True}
                except ValueError:
                    pass
            return {"behavior": "allow", "updatedInput": input_data}
    return {"behavior": "allow", "updatedInput": input_data}


def import_function(file_path, name):
    """_import_function (validation.py)."""
    module_name = f"interfaces_{name}_{id(file_path)}"
    if module_name in sys.modules:
        del sys.modules[module_name]
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if spec is None or spec.loader is None:
        raise ImportError(MCE.no_spec(path=file_path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as e:
        del sys.modules[module_name]
        raise ImportError(MCE.exec_failed(error=e))
    if not hasattr(module, name):
        del sys.modules[module_name]
        raise ImportError(MCE.no_attribute(name=name))
    return getattr(module, name)


def validate(folder, sigs):
    """validate_interfaces: -> ошибки (пусто — прошло). Каждый интерфейс — interfaces/<имя>.py с функцией тех же
    параметров и return со значением; модуль исполняется в процессе, как у апстрима."""
    folder = Path(folder)
    if not (folder / "interfaces").exists():
        return [MCE.no_interfaces()]
    errors = []
    if not (folder / "interfaces" / "__init__.py").exists():
        errors.append(MCE.no_init())
    for sig in sigs:
        error = validate_one(folder, sig)
        if error:
            errors.append(MCE.interface_error(name=sig.name, error=error))
    return errors


def validate_one(folder, sig):
    """_validate_single_interface: текст ошибки или None."""
    file_path = folder / "interfaces" / f"{sig.name}.py"
    if not file_path.exists():
        return MCE.no_file(name=sig.name)
    try:
        tree = ast.parse(file_path.read_text(encoding="utf-8"))
    except SyntaxError as e:
        return MCE.syntax_error(name=sig.name, error=e)
    except Exception as e:
        return MCE.parse_failed(name=sig.name, error=e)
    node = next((n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == sig.name), None)
    if node is None:
        return MCE.no_function(name=sig.name)
    expected, actual = [n for n, _, _ in sig.inputs], [a.arg for a in node.args.args]
    if actual != expected:
        return MCE.mismatch(expected=", ".join(expected), actual=", ".join(actual))
    if not any(isinstance(n, ast.Return) and n.value is not None for n in ast.walk(node)):
        return MCE.no_return(name=sig.name)
    try:
        import_function(file_path, sig.name)
    except Exception as e:
        return MCE.import_failed(error=e)
    return None


def load_interfaces(folder, sigs):
    """load_interfaces (eval.py) и load_interfaces_from_init (validation.py): функции из interfaces/__init__.py,
    папка под-итерации — в sys.path, как у апстрима. Нет интерфейсов у задачи — {}; нет __init__.py —
    FileNotFoundError."""
    if not sigs:
        return {}
    folder = Path(folder)
    init = folder / "interfaces" / "__init__.py"
    if not init.exists():
        raise FileNotFoundError(f"No interfaces found in {folder}. Expected interfaces/__init__.py")
    module_name = f"interfaces_module_{id(folder)}"
    if module_name in sys.modules:
        del sys.modules[module_name]
    spec = importlib.util.spec_from_file_location(module_name, init)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load spec for {init}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))
    try:
        spec.loader.exec_module(module)
    except Exception as e:
        raise ImportError(f"Failed to load interfaces module: {e}")
    names = module.__all__ if hasattr(module, "__all__") else [n for n in dir(module) if not n.startswith("_")]
    return {n: getattr(module, n) for n in names if callable(getattr(module, n, None))}


class Folder:
    """Память базового агента MCE апстрима: папка под-итерации на диске (context/, interfaces/, навык). На батче —
    data/train.json с итогами батча (format_result_for_training) и сессия базового агента Claude SDK
    (run_base_agent: промпт с интерфейсами задачи, cwd — папка под-итерации, проект .claude/ — навык; с
    интерфейсами — проверка и до 3 ответов с ошибками проверки). Версия памяти — путь папки."""
    requires = frozenset()

    def __init__(self):
        self.ws, self.path, self.loaded = None, None, None

    def begin(self, k):
        pass

    def at(self, ws, path):
        """Текущая папка; интерфейсы перечитываются при следующем показе."""
        self.ws, self.path, self.loaded = ws, path, None

    def interfaces(self, task):
        """Интерфейсы папки (load_interfaces один раз на батч или val, как у апстрима); нет — {}."""
        if self.loaded is None:
            try:
                self.loaded = load_interfaces(self.path, signatures(task)) if self.path else {}
            except FileNotFoundError:
                self.loaded = {}
        return self.loaded

    def files(self):
        if self.path is None:
            return {}
        return {str(p.relative_to(self.path)): p.read_text(errors="replace") for part in ("context", "interfaces")
                for p in sorted((self.path / part).rglob("*")) if p.is_file() and "__pycache__" not in p.parts}

    def records(self):
        return [Record(p, t) for p, t in self.files().items()]

    def chars(self):
        return sum(len(t) for t in self.files().values())

    def key(self):
        return str(self.path) if self.path else ""

    def dump(self):
        return [dict(kind="file", id=p, text=t) for p, t in self.files().items()]

    def learn(self, ex, extractions):
        """Под-итерация: train.json батча, затем базовый агент; не прошёл проверку — ошибка, как у апстрима."""
        groups = [x.group for x in extractions]
        field = "symptoms" if variant("mce", ex.task) == "symptom" else "question"
        (self.path / "data").mkdir(exist_ok=True)
        (self.path / "data" / "train.json").write_text(train_json(ex, groups, [g.item["id"] for g in groups], field),
                                                        encoding="utf-8")
        if not base_agent(ex, self.ws, self.path):
            raise RuntimeError(f"Base-agent failed at {self.path.name}: validation failed after {VALIDATION_TRIES} attempts")
        self.loaded = None


def base_agent(ex, ws, folder):
    """run_base_agent: сессия Claude SDK в папке под-итерации; -> прошла ли проверка интерфейсов."""
    from claude_agent_sdk import ClaudeAgentOptions
    sigs = signatures(ex.task)
    prompt = CLAUDE_BASE.fill(task_instruction=render.task_instruction(ex.task), iter_dir=str(folder),
                              iter_name=folder.name, signatures=bool(sigs), interfaces=INTERFACES.fill(signatures=sigs))
    options = ClaudeAgentOptions(cwd=str(folder), setting_sources=["project"], allowed_tools=BASE_TOOLS,
                                 can_use_tool=partial(base_permission, iter_dir=folder))

    def feedback():
        if not sigs:
            return None
        errors = validate(folder, sigs)
        return INVALID.fill(errors=errors) if errors else None
    ok = ex.model.session(prompt, options, feedback, VALIDATION_TRIES if sigs else 1, ws.root)
    cleanup(folder, "base")
    return ok
