"""Память базового агента MCE (meta-context-engineering: mce/base_agent.py, prompts/; промпт mce_base.j2 —
апстрим без интерфейсов и утилит, DEVIATIONS MCE1, MCE2): файлы context/ (мир документов). На батче
(под-итерации) агент по навыку правит их файловыми инструментами, до 30 раундов; в папке под-итерации
iter{k}_sub{j} — навык (.agent/, только чтение), context/ и data/train.json с итогами только текущего батча."""
from .. import fs, prompts, render
from ..model import Call, messages, params
from . import Files

BASE = prompts.load("mce_base")
ROUNDS = 30
WORKSPACE = "/workspace"    # корень, как его видят агенты (E2B-пути апстрима)
SKILL = ".agent/skills/learning-context/SKILL.md"      # навык в папке под-итерации (MCE5)


def sub_folder(ex):
    """Папка под-итерации (get_sub_iteration_folder_name): итерация = проход, под-итерация = батч."""
    return f"iter{ex.epoch + 1}_sub{ex.i // ex.learner.every}"


class Context(Files):
    """Файлы context/ базового агента; train — data/train.json последнего батча."""
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
        mounts = {"context": fs.Mount(self), "data": fs.Mount(Files.of({"train.json": self.train}), "ro")}
        if ex.learner.skill:
            top, rest = SKILL.split("/", 1)
            mounts = {top: fs.Mount(Files.of({rest: ex.learner.skill}), "ro"), **mounts}
        prompt = BASE.fill(task_instruction=render.task_instruction(ex.task), iter_dir=f"{WORKSPACE}/{name}", iter_name=name)
        ex.model.ask(Call(messages(prompt), params(), tools=fs.TOOLS, deps=fs.FS(mounts, root=f"{WORKSPACE}/{name}"),
                          rounds=self.rounds))

    def folder(self):
        """Папка под-итерации для мета-агента: context/ и data/train.json."""
        out = {f"context/{p}": t for p, t in self.files.items()}
        return {**out, "data/train.json": self.train} if self.train else out
