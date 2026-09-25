"""MCE (meta-context-engineering: mce/main.py, utils.py, meta_agent.py, base_agent.py, prompts/). Промпты
ace/prompts/mce_*.j2 — апстрим дословно в режиме без интерфейсов, без утилит (DEVIATIONS MCE1, MCE2).

mce = Meta(базовый агент с файлами):
    мета        итерация = проход; в начале итерации мета-агент с файлами (корень /workspace, как E2B-пути
                апстрима) читает meta_agent/ (train.jsonl, evaluations.json, skills/iter*/SKILL.md) и папки прошлых
                под-итераций и пишет SKILL.md в iter{k}_sub0/.claude/skills/learning-context/ (wrap.Meta); в конце
                прохода val, следующая итерация начинается с лучшей по val из пройденных (строго больше, при
                равенстве первая)
    память      файлы context/ (мир документов); их заводит и правит базовый агент по навыку файловыми
                инструментами, до 30 раундов; под-итерация = батч: папка iter{k}_sub{j} с навыком (.claude/, только
                чтение), context/ и data/train.json — итоги только текущего батча (только чтение)
    показ       все файлы context/ (интерфейса get_context, который апстрим пишет кодом, нет: MCE1)
    извлечение  нет: память читает сырое
    когда учится  батч 20; неполный батч применяется в конце прохода
Параметры scripts/train_symptom_diagnosis.sh: 3 итерации, train 50 батчами по 25, val 20; у нас 40 батчами
по 20 и val 10.

mce_ace = Meta(ACE): тот же мета-агент (промпт mce_meta_ace — про рефлектор и куратор ACE), навык идёт в
системные промпты рефлектора и куратора ACE; в папках под-итераций только навык. Нового в сравнении нет, кроме
меты: ученик — ace как есть.
"""
from .. import fs, prompts, render
from ..extract import Raw
from ..learner import Learner, swap
from ..memory import Files
from ..show import Whole
from ..wrap import SKILL, Meta, sub_folder
from .ace import ace

META, META_ACE, BASE = prompts.load("mce_meta"), prompts.load("mce_meta_ace"), prompts.load("mce_base")
MISSING = prompts.load("mce_skill_missing")

BATCH, ROUNDS, ITERATIONS = 20, 30, 3
ATTEMPTS = 3                # max_validation_attempts мета-агента: SKILL.md не записан — просьба записать
WORKSPACE = "/workspace"    # корень, как его видят агенты (E2B-пути апстрима)


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


def store(files):
    """Папка только на чтение из словаря путь -> текст."""
    out = Files("folder")
    out.files = dict(files)
    return out


def meta_agent(template):
    """author для Meta — мета-агент с файлами (run_meta_agent): читает всё в workspace (meta_agent/ и папки
    прошлых под-итераций), пишет SKILL.md в папку первой под-итерации. Не записал — до ATTEMPTS раз просьба в
    том же разговоре; так и не записал — навык прошлой итерации."""
    def author(ex, history):
        name = f"iter{len(history) + 1}_sub0"
        out = Files("skill")
        mounts = {"meta_agent": fs.Mount(reference(ex, history), "ro")}
        mounts.update({n: fs.Mount(store(f), "ro") for h in history for n, f in h.folders.items()})
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


class Context(Files):
    """Файлы context/ базового агента. На батче (под-итерации) агент по навыку правит их инструментами; итоги
    батча — data/train.json (только текущий батч), навык — .claude/skills/learning-context/SKILL.md."""
    def __init__(self, rounds=ROUNDS):
        super().__init__("context")
        self.rounds, self.train = rounds, ""

    def learn(self, ex, extractions):
        groups = [x.group for x in extractions]
        done, eps = ex.i + 1, [g.episodes[g.chosen] for g in groups]
        acc = sum(bool(e.ok) for e in eps) / len(eps) if eps else 0.0
        # id — место вопроса в проходе (порядок train у нас один и тот же), вопрос — поле question
        results = [dict(id=done - len(groups) + n, question=g.question, ground_truth=g.target, llm_prediction=e.answer,
                        is_correct=bool(e.ok)) for n, (g, e) in enumerate(zip(groups, eps))]
        self.train = render.train_json(dict(train_accuracy=acc, train_metrics=dict(accuracy=acc), train_total=len(eps),
                                            train_errors=0, batch_idx=ex.i // ex.learner.every, cumulative_rollouts=done),
                                       results)
        name = sub_folder(ex)
        mounts = {"context": fs.Mount(self), "data": fs.Mount(store({"train.json": self.train}), "ro")}
        if ex.learner.skill:
            mounts = {".claude": fs.Mount(store({SKILL.split("/", 1)[1]: ex.learner.skill}), "ro"), **mounts}
        prompt = BASE.fill(task_instruction=render.task_instruction(ex.task), iter_dir=f"{WORKSPACE}/{name}", iter_name=name)
        ex.model.run("", prompt, tools=fs.TOOLS, deps=fs.FS(mounts, root=f"{WORKSPACE}/{name}"), rounds=self.rounds)

    def folder(self):
        """Папка под-итерации для мета-агента: context/ и data/train.json."""
        out = {f"context/{p}": t for p, t in self.files.items()}
        return {**out, "data/train.json": self.train} if self.train else out


base = Learner("mce_base", memory=Context(), show=Whole(line=render.plain, sep="\n\n"), extract=Raw(), every=BATCH,
               flush=True, epochs=ITERATIONS)
mce = Meta(base, meta_agent(META), "mce")
mce_ace = Meta(swap(ace, epochs=ITERATIONS), meta_agent(META_ACE), "mce_ace")
