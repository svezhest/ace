"""MCE апстрима (meta-context-engineering: mce/utils.py, main.py, env/base.py, prompts/): общее для памяти (базовый
агент) и меты (мета-агент) — пути и имена папок под-итераций, навык в папке, интерфейсы задачи, инструкция задачи
агентам, workspace на диске и уборка папки после агента, утилиты агентов в процессе стенда."""
import json
import shutil
import sys
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from types import ModuleType

import numpy as np
from openai.lib._parsing._completions import type_to_response_format_param
from pydantic import BaseModel, Field

from .. import prompts, render
from ..model import Call, Reader, messages
from ..render import MCE
from ..tasks import variant

ROUNDS = 30                 # раундов файловых инструментов у агентов mce_fs
WORKSPACE = "/workspace"    # корень, как его видят агенты (E2B-пути апстрима)
SKILL = ".agent/skills/learning-context/SKILL.md"      # навык в папке под-итерации (MCE5)
CLAUDE_SKILL = ".claude/skills/learning-context/SKILL.md"
# mce/workspace_utils апстрима дословно: копия в utils/ под-итерации
UTILS = Path(__file__).parent.parent / "memory" / "mce_utils"


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


# Утилиты агентов (mce/workspace_utils: llm.py, embedding.py) в процессе стенда. Код интерфейсов исполняется здесь
# (load_interfaces, проверка базового агента), и у апстрима `from utils.llm import call_llm` в нём — законная часть
# метода: промпты агентов предлагают звать LLM из кода. Утилиты апстрима шли бы через langchain по OPENROUTER_*
# процесса и .env выше по дереву (load_dotenv(override=True)) — мимо модели стенда и расхода. Поэтому в процессе
# стенда пакет utils — этот: те же функции с теми же параметрами запроса, но на модели стенда (адрес и имя — её),
# в её расходе. Копии utils/ в папках под-итераций в процессе не исполняются (их зовёт только Bash агентов, там
# адрес — claude.env); в venv стенда нет ни langchain_openai, ни dotenv.

MAX_LLM_CALLS = 100
LLM_TRIES = 3               # with_retry(stop_after_attempt=3)
EMBEDDING_MODEL = "text-embedding-3-small"


class TextResponse(BaseModel):
    """Simple text response from LLM."""
    response: str = Field(description="The LLM's response text")


def ask_llm(model, prompt, schema):
    """Запрос llm.with_structured_output(schema) апстрима (ChatOpenAI, temperature=0): одно сообщение user, без
    предела генерации; на проводе схема — response_format json_schema strict, как её шлёт клиент openai у
    langchain, на pydantic-ai — его структурированный вывод. Не ответил или ответ не по схеме — ещё раз, до
    LLM_TRIES; последняя ошибка — наружу."""
    params = {"temperature": 0.0}
    if model.on_wire:
        params["response_format"] = type_to_response_format_param(schema)
    call = Call(messages(prompt), params, Reader(schema=schema))
    for attempt in range(LLM_TRIES):
        try:
            out = model.ask(call).output
        except Exception:
            if attempt == LLM_TRIES - 1:
                raise
            continue
        if out is not None:
            return out
    raise ValueError(f"LLM output does not match {schema.__name__}")


def batch(model, prompts, schema):
    """call_llm_async апстрима; промпты по очереди, а не 50 разом."""
    if len(prompts) > MAX_LLM_CALLS:
        raise ValueError(f"Number of prompts ({len(prompts)}) exceeds maximum allowed per batch ({MAX_LLM_CALLS})")
    return [ask_llm(model, p, schema) for p in prompts]


async def call_llm_async(model, prompts, schema):
    return batch(model, prompts, schema)


def call_llm(model, prompts, schema=None):
    """call_llm апстрима: строка — один ответ, список — список; без схемы — текст (TextResponse.response)."""
    is_single = isinstance(prompts, str)
    results = batch(model, [prompts] if is_single else prompts, schema if schema is not None else TextResponse)
    if schema is None:
        results = [r.response for r in results]
    return results[0] if is_single else results


def compute_embedding_similarity(model, strings_a, strings_b):
    """Косинусная близость эмбеддингов (embedding.py апстрима): модель эмбеддингов апстрима по имени, через
    model.embed."""
    a = np.array(model.embed(strings_a, EMBEDDING_MODEL))
    b = np.array(model.embed(strings_b, EMBEDDING_MODEL))
    a = a / np.linalg.norm(a, axis=1, keepdims=True)
    b = b / np.linalg.norm(b, axis=1, keepdims=True)
    return a @ b.T


def utilities(model):
    """Пакет utils на модели model — в sys.modules: интерфейсы, загруженные после этого, берут его."""
    llm = ModuleType("utils.llm")
    llm.TextResponse, llm.MAX_LLM_CALLS = TextResponse, MAX_LLM_CALLS
    llm.call_llm, llm.call_llm_async = partial(call_llm, model), partial(call_llm_async, model)
    embedding = ModuleType("utils.embedding")
    embedding.EMBEDDING_MODEL = EMBEDDING_MODEL
    embedding.compute_embedding_similarity = partial(compute_embedding_similarity, model)
    utils = ModuleType("utils")
    utils.__path__ = []         # пакет: других модулей в нём нет
    utils.llm, utils.embedding = llm, embedding
    sys.modules.update({"utils": utils, "utils.llm": llm, "utils.embedding": embedding})
