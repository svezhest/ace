"""Мета-уровень: обёртки над учеником. Обёртка перехватывает свои хуки, остальное (уровни, хуки, снимки) —
у ученика; цикл видит обёртку как ученика.

    Gate(ученик)            правка батча остаётся, только если на val не хуже (решения — в gated, в лог)
    Meta(ученик, author)    итерация = проход: в начале итерации author пишет навык по истории итераций в
                            ученик.skill; в конце прохода — val, запись в историю и откат к лучшей по val
    Hooks(ученик)           хуки по ошибкам инструментов — ace/hooks.py

Навык ученик подставляет в свои промпты обучения сам (skilled): у базового агента MCE — инструкция правки
файлов, у ACE — добавка к системным промптам рефлектора и куратора."""
import copy
from dataclasses import dataclass, field

from . import prompts
from .learner import swap


def skilled(system, ex):
    """Системный промпт обучения с навыком от мета-уровня; без навыка — как был."""
    skill = getattr(getattr(ex, "learner", None), "skill", "")
    return system + "\n\n" + prompts.text("meta_skill", skill=skill) if skill else system


class Wrapper:
    def __init__(self, inner, name=None):
        self.inner, self.name = inner, name or inner.name

    def __getattr__(self, attr):
        if attr.startswith("__") or attr == "inner":
            raise AttributeError(attr)
        return getattr(self.inner, attr)

    def swap(self, name=None, **levels):
        """Та же обёртка над учеником с заменёнными уровнями."""
        out = copy.deepcopy(self)
        out.inner, out.name = swap(self.inner, **levels), name or self.name
        return out


def correct(results):
    return sum(c for c, _ in results)


def truncated(results):
    return sum(t for _, t in results)


class Gate(Wrapper):
    """Правка на батче принимается, если на val верных не меньше и обрывов не больше, чем до неё. Если память
    не изменилась, проверять нечего."""
    def __init__(self, inner, name=None):
        super().__init__(inner, name)
        self.gated = []

    def on_batch(self, ex, groups):
        before, key = self.inner.snapshot(), self.inner.key()
        self.inner.on_batch(ex, groups)
        if key is not None and self.inner.key() == key:
            return
        after, new = ex.evaluate(), self.inner.snapshot()
        self.inner.restore(before)
        prev = ex.evaluate()
        ok = correct(after) >= correct(prev) and truncated(after) <= truncated(prev)
        if ok:
            self.inner.restore(new)
        self.gated.append(ok)


SKILL = ".agent/skills/learning-context/SKILL.md"      # навык в папке под-итерации MCE (MCE5)


def sub_folder(ex):
    """Папка под-итерации MCE (get_sub_iteration_folder_name): итерация = проход, под-итерация = батч."""
    return f"iter{ex.epoch + 1}_sub{ex.i // ex.learner.every}"


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
