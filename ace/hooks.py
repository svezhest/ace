"""Хуки по ошибкам инструментов: обёртка Hooks(ученик) = извлечение + память + показ поверх любого ученика.

    извлечение  learn="model": после вопроса модель выводит уроки по ошибкам попытки (hook_reflect), в память
                идут уверенные (high), чей trigger дословно есть в тексте ошибки; модели показываются и хуки,
                которые не помогли (их можно переписать). learn="raw": без модели, как пары DC — ошибка и
                следующий вызов, который прошёл. Исходы показа (fired) — метки хуков.
    память      уроки с триггером; исходы показа — в журнал; хук с тем же trigger и другим текстом — новая
                запись со счётчиками с нуля; prune — хук уходит, когда вредных исходов не меньше prune и больше
                полезных
    показ       show="after" — после шага с ошибкой хуки, чей trigger есть в тексте ошибки, сообщением в конец
                истории (Patch(append)): исправление. Исход — по следующему шагу: помог, если его ошибка не
                повторилась; без следующего шага исхода нет. show="system" — все хуки в системном промпте с
                начала попытки: предотвращение. Исход — по попытке: помог, если его ошибки в ней не было.
Ошибки шага бывают только у решателя с инструментами: ученику нужна среда с исполнением кода."""
import copy
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel

from . import prompts, render
from .extract import LABELS, TRIGGER, Extraction, Extractor, Labels, missing, scores
from .memory import Ids, Lesson, Lessons
from .show import AfterError, Show, Whole
from .wrap import Wrapper

REFLECT = prompts.load("hook_reflect")
LEVELS = ("low", "medium", "high")
PRUNE = 2
ERROR_KIND_CHARS = 60       # trigger хука из траектории, если имени исключения нет


@dataclass(frozen=True, eq=False)
class Hook(Lesson):
    """Урок по ошибке: показывается, когда текст ошибки содержит trigger."""
    trigger: str = ""

    def head(self):
        return self.trigger

    def fires(self, text):
        return self.trigger.lower() in text.lower()

# извлечение


class HookLesson(BaseModel):
    trigger: str
    lesson: str
    confidence: Literal["low", "medium", "high"]


class HookLessons(BaseModel):
    hooks: list[HookLesson] = []


def failures(ep):
    return [s for s in ep.steps if s.failed]


def outcomes(group):
    """Исходы показанных хуков во всех попытках группы -> метки."""
    fired = [f for e in group.episodes for f in e.fired]
    return Labels([id for id, ok in fired if ok], [id for id, ok in fired if not ok])


class FromErrors(Extractor):
    """Уроки по ошибкам каждой попытки группы: learn(ex, эпизод, память) -> [(trigger, текст)]."""
    gives = frozenset({TRIGGER, LABELS})

    def __init__(self, learn):
        self.learn = learn

    def __call__(self, ex, group, memory):
        hooks = [h for e in group.episodes if failures(e) for h in self.learn(ex, e, memory)]
        labels = outcomes(group)
        if not hooks and not labels.helpful and not labels.harmful:
            return None
        return Extraction(group, [t for _, t in hooks], scores(group), {TRIGGER: [t for t, _ in hooks], LABELS: labels})


def by_model(ex, ep, memory, level="high"):
    """Уверенные уроки модели, чей trigger есть в тексте одной из ошибок попытки."""
    missed = [memory.get(i) for i in dict.fromkeys(i for i, ok in ep.fired if not ok) if memory.get(i)]
    r = ex.model.run("", REFLECT.fill(question=ep.question, errors=render.failures(failures(ep)), output=ep.output,
                                      verdict=render.verdict(ep.ok, ep.target), missed=render.hooks(missed)),
                     output=HookLessons).output
    errors = [s.result.lower() for s in failures(ep)]
    return [(h.trigger.strip(), h.lesson.strip()) for h in (r.hooks if r else [])
            if LEVELS.index(h.confidence) >= LEVELS.index(level) and h.trigger.strip()
            and any(h.trigger.strip().lower() in e for e in errors)]


def error_kind(result):
    """Последняя строка ошибки до двоеточия (ZeroDivisionError) или её начало."""
    line = [l for l in result.strip().splitlines() if l.strip()][-1].strip()
    head = line.split(":")[0].strip()
    return head if head and head != "Error" and " " not in head else line[:ERROR_KIND_CHARS]


def by_trajectory(ex, ep, memory):
    """Ошибка и следующий вызов, который прошёл без ошибки."""
    return [(error_kind(s.result), render.raw_hook(nxt.tool, nxt.args))
            for s, nxt in zip(ep.steps, ep.steps[1:]) if s.failed and not nxt.failed]


LEARN = {"model": by_model, "raw": by_trajectory}

# память


class HookBook(Lessons):
    def __init__(self, prune=PRUNE):
        super().__init__("hook", record=Hook, ids=Ids("h"))     # свои id: в показе рядом с записями ученика
        self.prune_at = prune
        self.requires = frozenset({TRIGGER, LABELS}) if prune else frozenset({TRIGGER})

    def learn(self, ex, extractions):
        for x in extractions:
            if LABELS in x.extras:
                self.count(x.extras[LABELS].helpful, x.extras[LABELS].harmful)
            for text, trigger in zip(x.lessons, x.extras[TRIGGER]):
                old = next((r for r in self.items if r.trigger.lower() == trigger.lower()), None)
                if old is None:
                    self.add(text, trigger=trigger)
                elif old.text != text:
                    self.update(old.id, text, trigger=trigger)
        if self.prune_at:
            self.prune(lambda r: r.harmful >= self.prune_at and r.harmful > r.helpful)

# показ


def fired(records, step):
    """Хуки, показанные после шага step."""
    return [r for r in records if r.fires(step.result)] if step.failed else []


AFTER = AfterError(Show(), lambda memory: memory.records(), trigger=lambda r: r.trigger)
SYSTEM = Whole(layout=lambda records, memory: render.hooks(records), head=prompts.text("hook_system_intro"))

# обёртка


class Hooks(Wrapper):
    def __init__(self, inner, name=None, learn="model", prune=PRUNE, show="after"):
        super().__init__(inner, name)
        self.hooks, self.extract_hooks, self.show_at = HookBook(prune), FromErrors(LEARN[learn]), show
        self.pending_hooks = []
        lack = missing(self.hooks, self.extract_hooks)
        if lack:
            raise ValueError(f"{self.name}: память хуков требует {', '.join(sorted(lack))}")

    def prompt(self, ex, item, k, memory=None):
        p = self.inner.prompt(ex, item, k, memory)
        if self.show_at == "system":
            mine = SYSTEM.prompt(ex, self.hooks, item, k)
            p.system += mine.system
            p.shown = p.shown + mine.shown
        return p

    def watches_steps(self):
        return True

    def on_step(self, ex, attempt, step):
        patch = self.inner.on_step(ex, attempt, step)
        if self.show_at != "after":
            return patch
        if len(attempt.steps) > 1:
            attempt.fired += [(r.id, not (step.failed and r.fires(step.result)))
                              for r in fired(self.hooks.records(), attempt.steps[-2])]
        mine = AFTER.on_step(ex, self.hooks, attempt, step)
        return mine if patch is None else patch.merge(mine) if mine else patch

    def on_attempt(self, ex, episode):
        self.inner.on_attempt(ex, episode)
        if self.show_at == "system":
            errors = [s.result for s in failures(episode)]
            episode.fired += [(id, not any(self.hooks.get(id).fires(e) for e in errors))
                              for id in episode.shown if self.hooks.get(id)]

    def on_question(self, ex, group):
        self.inner.on_question(ex, group)
        x = self.extract_hooks(ex, group, self.hooks)
        if x:
            self.pending_hooks.append(x)

    def on_batch(self, ex, groups):
        self.inner.on_batch(ex, groups)
        if self.pending_hooks:
            self.hooks.learn(ex, self.pending_hooks)
        self.pending_hooks = []

    def on_pass(self, ex):
        self.inner.on_pass(ex)
        self.pending_hooks = []

    def snapshot(self):
        return self.inner.snapshot(), copy.deepcopy(self.hooks)

    def restore(self, snapshot):
        self.inner.restore(snapshot[0])
        self.hooks = copy.deepcopy(snapshot[1])

    def key(self):
        key = self.inner.key()
        return None if key is None else (key, self.hooks.key())

    def dump(self):
        return self.inner.dump() + self.hooks.dump()
