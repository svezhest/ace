"""MCE (meta-context-engineering: mce/main.py, utils.py, meta_agent.py; промпты mce_meta*.j2 — апстрим дословно
в режиме без интерфейсов, без утилит, DEVIATIONS MCE1, MCE2).

    Meta(ученик, author)    итерация = проход по train батчами ученика (батч — под-итерация); перед первой попыткой
                            прохода author пишет навык; в конце прохода val, следующая итерация — с лучшей по val
    MetaAgent(шаблон)       author: мета-агент с файлами (корень /workspace, как E2B-пути апстрима) читает
                            meta_agent/ (train.jsonl, evaluations.json, skills/iter*/SKILL.md) и папки прошлых
                            под-итераций и пишет SKILL.md в iter{k}_sub0/.agent/skills/learning-context/"""
import atexit
import os
import random
import shutil
import tempfile
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path

from .. import config, fs, prompts, render
from ..memory import Files
from ..model import Call, claude, messages, params
from ..memory.mce import CLAUDE_SKILL, ROUNDS, SKILL, WORKSPACE, Workspace, cleanup, folder_name, signatures, sub_folder
from ..loop import best_index
from . import Wrapper, correct

META = prompts.load("mce_meta")
META_ACE = prompts.load("mce_meta_ace")
MISSING = prompts.load("mce_skill_missing")
SKILL_TRIES = 3             # max_validation_attempts мета-агента: ответов, пока SKILL.md не записан


@dataclass
class Iteration:
    """Итерация меты: навык (text), точность на train за проход и на val, версия памяти ученика после неё, сколько
    вопросов val и train (rollouts), папки под-итераций: имя -> {путь: текст} (их видит мета-агент)."""
    text: str
    train: float
    val: float
    memory: object
    val_total: int = 0
    rollouts: int = 0
    folders: dict = field(default_factory=dict)
    folder: str = ""            # MCE апстрима: последняя папка под-итерации на диске

    def dump(self, i):
        return dict(kind="iterations", id=f"iter{i}", text=self.text, train=self.train, val=self.val, folder=self.folder)


def offline_only(wrapper):
    """MCE учится только на train: итерация — проход по train, выбор — по val."""
    if not wrapper.inner.protocol.val:
        raise ValueError(f"{wrapper.name}: MCE — только офлайн с val (итерация — проход по train)")


def share_correct(results):
    """Доля верных по (верно, обрыв) вопросов val."""
    return correct(results) / len(results) if results else 0.0


class Meta(Wrapper):
    """MCE (mce/main.py): итерация = проход по train батчами ученика (батч — под-итерация). Перед первой попыткой
    прохода author(ex, история) пишет навык; train итерации — доля верных за весь проход (среднее по батчам с весом,
    как aggregate_iteration_results). После каждого батча — снимок папки под-итерации: навык и то, что память
    ученика отдаёт как папку (folder()). В конце прохода val, итерация — в историю, следующая начинается с лучшей
    по val из уже пройденных (_find_best_iteration). Нулевой итерации (val пустой памяти) нет: апстрим по
    умолчанию начинает с iter1, а iter0 в выборе не участвует."""
    def __init__(self, inner, author, name=None):
        super().__init__(inner, name)
        self.author = author
        self.history = []       # Iteration по порядку
        self.new_pass()

    def new_pass(self):
        """Счётчики прохода: верных и вопросов train, папки под-итераций."""
        self.right = 0
        self.seen = 0
        self.folders = {}

    def check(self):
        offline_only(self)

    def on_pass_start(self, ex):
        """Начало прохода открывает итерацию: навык до всего обучения прохода."""
        ex.skill = self.author(ex, self.history)
        self.inner.on_pass_start(ex)

    def on_batch(self, ex, groups):
        self.right += sum(bool(g.episodes[g.chosen].ok) for g in groups)
        self.seen += len(groups)
        self.inner.on_batch(ex, groups)
        memory = self.inner.memory
        folder = memory.folder() if hasattr(memory, "folder") else {}      # память, отдающая себя папкой (Context)
        if ex.skill:
            folder = {SKILL: ex.skill, **folder}
        self.folders[sub_folder(ex)] = folder

    def on_pass(self, ex):
        self.inner.on_pass(ex)
        val = ex.evaluate()
        train = self.right / self.seen if self.seen else 0.0
        self.history.append(Iteration(ex.skill, train=train, val=share_correct(val), memory=self.inner.snapshot(),
                                      val_total=len(val), rollouts=self.seen, folders=self.folders))
        self.inner.restore(self.history[best(self.history)].memory)
        self.new_pass()

    def dump(self):
        return self.inner.dump() + [h.dump(i) for i, h in enumerate(self.history, 1)]


def best(history):
    """Номер лучшей по val итерации (строго больше, при равенстве первая)."""
    return best_index([h.val for h in history])


def evaluations(history):
    """evaluations.json (aggregate_iteration_results): итерации с первой, метрика accuracy."""
    return {f"iter{i}": dict(train_accuracy=h.train, train_metrics=dict(accuracy=h.train), val_accuracy=h.val,
                             val_metrics=dict(accuracy=h.val), val_total=h.val_total, total_rollouts=h.rollouts,
                             num_sub_iters=len(h.folders), last_sub_folder=next(reversed(h.folders), f"iter{i}"))
            for i, h in enumerate(history, 1)}


def skills(history):
    """Навыки итераций (meta_agent/skills/iter{i}/SKILL.md); пустого навыка нет и в архиве."""
    return {f"iter{i}": h.text for i, h in enumerate(history, 1) if h.text}


def reference(ex, history):
    """meta_agent/ (только чтение): весь train, evaluations.json после первой итерации, архив навыков."""
    ref = Files("meta_agent")
    ref.write("train.jsonl", render.jsonl(ex.task.load("train")))
    if history:
        ref.write("evaluations.json", render.pretty_json(evaluations(history)))
    for it, text in skills(history).items():
        ref.write(f"skills/{it}/SKILL.md", text)
    return ref


class MetaAgent:
    """author для Meta — мета-агент с файлами (run_meta_agent): читает всё в workspace (meta_agent/ и папки
    прошлых под-итераций), пишет SKILL.md в папку первой под-итерации. Не записал — до SKILL_TRIES раз просьба в
    том же разговоре; так и не записал — навык прошлой итерации."""
    def __init__(self, template):
        self.template = template

    def __call__(self, ex, history):
        name = f"iter{len(history) + 1}_sub0"
        out = Files("skill")
        mounts = {"meta_agent": fs.Mount(reference(ex, history), "ro")}
        for h in history:
            for folder, files in h.folders.items():
                mounts[folder] = fs.Mount(Files.of(files), "ro")
        mounts[name] = fs.Mount(out)
        path = f"{WORKSPACE}/{name}/{SKILL}"
        database = render.skill_database(evaluations(history), skills(history), len(history) + 1)
        user = self.template.fill(task_instruction=render.task_instruction(ex.task), workspace=WORKSPACE, iter_name=name,
                                  skill_output_path=path, skill_database=database)
        conversation = None     # история разговора: просьба записать идёт в тот же разговор
        for _ in range(SKILL_TRIES):
            call = Call(messages(user), params(), tools=fs.TOOLS, deps=fs.FS(mounts, root=WORKSPACE), rounds=ROUNDS,
                        history=conversation)
            reply = ex.model.ask(call)
            if out.read(SKILL) is not None:
                return out.read(SKILL)
            user = MISSING.fill(expected_path=path)
            conversation = reply.messages
        return history[-1].text if history else ""


# MCE апстрима на Claude Agent SDK (mce/main.py run_iteration, meta_agent.py): workspace на диске, мета-агент и
# базовый агент — Claude SDK (model/claude.py), память ученика — папка под-итерации (memory/mce.py: Folder).

META_TOOLS = ["Read", "Write", "Edit", "Bash", "Glob", "Grep", "Task", "TaskOutput", "ExitPlanMode", "TodoWrite",
              "KillShell", "EnterPlanMode"]
CLAUDE_META, CLAUDE_META_INTERFACES = prompts.load("mce_claude_meta"), prompts.load("mce_claude_meta_interfaces")
CLAUDE_MISSING = prompts.load("mce_claude_skill_missing")
MCE = prompts.macros("mce_strings")


async def meta_permission(tool_name, input_data, context, iter_dir):
    """_meta_agent_permission_handler апстрима дословно: как и у базового агента, отвечает dict и зовётся только
    для инструментов вне allowed_tools (memory/mce.py: base_permission)."""
    workspace_base = iter_dir.parent.resolve()
    iter_dir = iter_dir.resolve()
    if tool_name not in META_TOOLS:
        return {"behavior": "deny", "message": MCE.meta_tool_denied(tool=tool_name, allowed=", ".join(META_TOOLS)),
                "interrupt": False}
    if tool_name in ["Read", "Write", "Edit", "Glob", "Grep"]:
        file_path = input_data.get("file_path") or input_data.get("path")
        if file_path:
            if not Path(file_path).is_absolute():
                resolved = (workspace_base / file_path).resolve()
            else:
                resolved = Path(file_path).resolve()
            if tool_name in ["Read", "Glob", "Grep"]:
                try:
                    resolved.relative_to(workspace_base)
                    return {"behavior": "allow", "updatedInput": input_data}
                except ValueError:
                    return {"behavior": "deny", "interrupt": True,
                            "message": MCE.meta_read_outside(workspace=workspace_base)}
            if tool_name in ["Write", "Edit"]:
                skills_dir = iter_dir / ".claude" / "skills"
                try:
                    resolved.relative_to(skills_dir)
                    return {"behavior": "allow", "updatedInput": input_data}
                except ValueError:
                    return {"behavior": "deny", "interrupt": True,
                            "message": MCE.meta_write_outside(folder=skills_dir)}
    return {"behavior": "allow", "updatedInput": input_data}


def claude_meta(ex, ws, folder, iteration):
    """run_meta_agent: сессия Claude SDK с cwd = workspace, промпт — build_meta_agent_prompt (локальные пути); нет
    SKILL.md — просьба в том же разговоре, до 3 ответов; так и не записал — ошибка, как у апстрима."""
    from claude_agent_sdk import ClaudeAgentOptions
    sigs = signatures(ex.task)
    skill = folder / CLAUDE_SKILL
    prompt = CLAUDE_META.fill(task_instruction=render.task_instruction(ex.task),
                              interfaces=CLAUDE_META_INTERFACES.fill(signatures=sigs), workspace=str(ws.base),
                              iter_name=folder.name, skill_output_path=f"{ws.base}/{folder.name}/{CLAUDE_SKILL}",
                              skill_database=render.skill_database(ws.evaluations(), ws.skills(), iteration))
    options = ClaudeAgentOptions(cwd=str(ws.base), allowed_tools=META_TOOLS,
                                 can_use_tool=partial(meta_permission, iter_dir=folder))

    def feedback():
        return None if skill.exists() else CLAUDE_MISSING.fill(expected_path=skill)
    ok = ex.model.session(prompt, options, feedback, SKILL_TRIES, ws.root)
    cleanup(folder)
    if not ok:
        raise RuntimeError(f"Meta-agent failed to generate SKILL.md after {SKILL_TRIES} attempts")
    return skill.read_text()


class Iterations(Wrapper):
    """MCE апстрима (mce/main.py): итерация = проход. В начале итерации — случайная выборка train (load_samples:
    random.sample n из всего train, затем shuffle), папка iter{k}_sub0 и мета-агент; батч = под-итерация: папка
    (у sub0 context/ и interfaces/ — из последней папки лучшей по val итерации, у iter1 — пустые; дальше — из
    прошлой под-итерации вместе с навыком), вопросы батча, train.json и базовый агент (Folder.learn). В конце
    прохода — val последней папкой, итерация — в meta_agent/evaluations.json и архив навыков, откат к лучшей по val
    (строго больше, при равенстве первая; iter0 не участвует). Workspace — root/workspace/<name>, по умолчанию
    <задача>-<pid>; без корня — временная папка, удаляется при выходе."""
    def __init__(self, inner, root=None, workspace=None, name=None):
        super().__init__(inner, name)
        self.root = root
        self.workspace = workspace
        self.ws = None          # Workspace на диске, создаётся при первой выборке
        self.history = []       # Iteration по порядку
        self.subs = []          # итоги батчей прохода (aggregate_iteration_results)

    def check(self):
        offline_only(self)

    def sample(self, ex, split, n):
        if self.ws is None:
            root = self.root or config.MCE_ROOT
            if root is None:
                root = tempfile.mkdtemp(prefix="mce-")
                atexit.register(shutil.rmtree, root, ignore_errors=True)
            # свой workspace на процесс: параллельные прогоны с общим корнем не стирают друг друга
            self.ws = Workspace(root, self.workspace or f"{ex.task.name}-{os.getpid()}")
            claude.prepare(root)
            self.ws.start(ex.task)
        samples = [dict(item, id=i) for i, item in enumerate(ex.task.load(split, whole=True))]
        if n and len(samples) > n:
            samples = random.sample(samples, n)
        random.shuffle(samples)
        return samples

    def on_batch_start(self, ex):
        """Батч — под-итерация: папка, у первой — мета-агент."""
        self.inner.on_batch_start(ex)
        iteration, sub = ex.epoch + 1, ex.batch
        folder = self.ws.create(iteration, sub)
        if sub == 0:
            ex.skill = claude_meta(ex, self.ws, folder, iteration)
            last = self.history[best(self.history)].folder if self.history else folder_name(0)
            source = self.ws.base / last
        else:
            source = self.inner.memory.path
            self.ws.copy_skills(source, folder)
        self.ws.setup(folder, source)
        self.inner.memory.at(self.ws, folder)

    def on_batch(self, ex, groups):
        right = sum(bool(g.episodes[g.chosen].ok) for g in groups)
        metrics = {"accuracy": right / len(groups)}
        self.subs.append(dict(batch_size=len(groups), metric=metrics["accuracy"], metrics=metrics))
        self.inner.on_batch(ex, groups)

    def on_pass(self, ex):
        self.inner.on_pass(ex)
        val = ex.evaluate()
        metrics = {"accuracy": share_correct(val)} if val else {}
        last = self.inner.memory.path
        train = self.ws.aggregate(ex.epoch + 1, self.subs, metrics, len(val), last)
        rollouts = sum(s["batch_size"] for s in self.subs)
        self.history.append(Iteration(ex.skill, train=train, val=metrics.get("accuracy", 0.0),
                                      memory=self.inner.snapshot(), val_total=len(val), rollouts=rollouts,
                                      folder=last.name))
        self.inner.restore(self.history[best(self.history)].memory)
        self.subs = []

    def dump(self):
        return self.inner.dump() + [h.dump(i) for i, h in enumerate(self.history, 1)]
