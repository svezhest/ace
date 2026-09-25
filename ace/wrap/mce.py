"""MCE (meta-context-engineering: mce/main.py, utils.py, meta_agent.py; промпты mce_meta*.j2 — апстрим дословно
в режиме без интерфейсов, без утилит, DEVIATIONS MCE1, MCE2).

    Meta(ученик, author)    итерация = проход по train батчами ученика (батч — под-итерация); перед первой попыткой
                            прохода author пишет навык; в конце прохода val, следующая итерация — с лучшей по val
    meta_agent(шаблон)      author: мета-агент с файлами (корень /workspace, как E2B-пути апстрима) читает
                            meta_agent/ (train.jsonl, evaluations.json, skills/iter*/SKILL.md) и папки прошлых
                            под-итераций и пишет SKILL.md в iter{k}_sub0/.agent/skills/learning-context/"""
from dataclasses import dataclass, field

from .. import fs, prompts, render
from ..memory import Files
from ..memory.mce import ROUNDS, SKILL, WORKSPACE, sub_folder
from . import Wrapper, correct

META, META_ACE = prompts.load("mce_meta"), prompts.load("mce_meta_ace")
MISSING = prompts.load("mce_skill_missing")
ATTEMPTS = 3                # max_validation_attempts мета-агента: SKILL.md не записан — просьба записать


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


def accuracy(results):
    return correct(results) / len(results) if results else 0.0


def best_iteration(vals):
    """_find_best_iteration: номер лучшей по val итерации; строго больше, при равенстве первая."""
    best, top = None, -1e9
    for i, v in enumerate(vals):
        if v > top:
            best, top = i, v
    return best


class Meta(Wrapper):
    """MCE (mce/main.py): итерация = проход по train батчами ученика (батч — под-итерация). Перед первой попыткой
    прохода author(ex, история) пишет навык; train итерации — доля верных за весь проход (среднее по батчам с весом,
    как aggregate_iteration_results). После каждого батча — снимок папки под-итерации: навык и то, что память
    ученика отдаёт как папку (folder()). В конце прохода val, итерация — в историю, следующая начинается с лучшей
    по val из уже пройденных (_find_best_iteration). Нулевой итерации (val пустой памяти) нет: апстрим по
    умолчанию начинает с iter1, а iter0 в выборе не участвует."""
    def __init__(self, inner, author, name=None):
        super().__init__(inner, name)
        self.author, self.history = author, []
        self.fresh, self.right, self.seen, self.folders = True, 0, 0, {}

    def prompt(self, ex, item, k, memory=None):
        """Первая попытка прохода при обучении открывает итерацию: навык до всего обучения прохода."""
        if ex.training and self.fresh:
            self.inner.skill = self.author(ex, self.history)
            self.fresh = False
        return self.inner.prompt(ex, item, k, memory)

    def on_batch(self, ex, groups):
        self.right += sum(bool(g.episodes[g.chosen].ok) for g in groups)
        self.seen += len(groups)
        self.inner.on_batch(ex, groups)
        folder = getattr(self.inner.memory, "folder", dict)()
        self.folders[sub_folder(ex)] = {SKILL: self.inner.skill, **folder} if self.inner.skill else folder

    def on_pass(self, ex):
        self.inner.on_pass(ex)
        val = ex.evaluate()
        self.history.append(Iteration(self.inner.skill, self.right / self.seen if self.seen else 0.0, accuracy(val),
                                      self.inner.snapshot(), len(val), self.seen, self.folders))
        self.inner.restore(self.history[best_iteration([h.val for h in self.history])].memory)
        self.fresh, self.right, self.seen, self.folders = True, 0, 0, {}

    def dump(self):
        return self.inner.dump() + [dict(kind="iterations", id=f"iter{i}", text=h.text, train=h.train, val=h.val)
                                    for i, h in enumerate(self.history, 1)]


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
        ref.write("evaluations.json", render.evaluations(evaluations(history)))
    for it, text in skills(history).items():
        ref.write(f"skills/{it}/SKILL.md", text)
    return ref


def meta_agent(template):
    """author для Meta — мета-агент с файлами (run_meta_agent): читает всё в workspace (meta_agent/ и папки
    прошлых под-итераций), пишет SKILL.md в папку первой под-итерации. Не записал — до ATTEMPTS раз просьба в
    том же разговоре; так и не записал — навык прошлой итерации."""
    def author(ex, history):
        name = f"iter{len(history) + 1}_sub0"
        out = Files("skill")
        mounts = {"meta_agent": fs.Mount(reference(ex, history), "ro")}
        mounts.update({n: fs.Mount(Files.of(f), "ro") for h in history for n, f in h.folders.items()})
        mounts[name] = fs.Mount(out)
        path = f"{WORKSPACE}/{name}/{SKILL}"
        user = template.fill(task_instruction=render.task_instruction(ex.task), workspace=WORKSPACE, iter_name=name,
                             skill_output_path=path, skill_database=render.skill_database(
                                 evaluations(history), skills(history), len(history) + 1))
        talk = None
        for _ in range(ATTEMPTS):
            reply = ex.model.run("", user, tools=fs.TOOLS, deps=fs.FS(mounts, root=WORKSPACE), rounds=ROUNDS, history=talk)
            if out.read(SKILL) is not None:
                return out.read(SKILL)
            user, talk = MISSING.fill(expected_path=path), reply.messages
        return history[-1].text if history else ""
    return author
