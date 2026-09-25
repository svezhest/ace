"""Извлечение хуков по ошибкам: уроки по ошибкам каждой попытки группы и исходы показанных хуков (метки).

    by_model        после вопроса модель выводит уроки по ошибкам попытки (hook_reflect); в память идут уверенные
                    (high), чей trigger дословно есть в тексте ошибки; модели показываются и хуки, которые не помогли
    by_trajectory   без модели, как пары DC: ошибка и следующий вызов, который прошёл"""
from typing import Literal

from pydantic import BaseModel

from .. import prompts, render
from ..model import Call, Reader, messages, params
from . import LABELS, TRIGGER, Extraction, Extractor, Labels, scores

REFLECT = prompts.load("hook_reflect")
LEVELS = ("low", "medium", "high")
ERROR_KIND_CHARS = 60       # trigger хука из траектории, если имени исключения нет


class HookLesson(BaseModel):
    trigger: str
    lesson: str
    confidence: Literal["low", "medium", "high"]


class HookLessons(BaseModel):
    hooks: list[HookLesson] = []


def failures(ep):
    """Шаги с ошибкой исполнения; ошибка вызова инструмента — не урок кода."""
    return [s for s in ep.steps if s.exec_error]


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
    prompt = REFLECT.fill(question=ep.question, errors=render.failed_steps(failures(ep)), output=ep.output,
                          verdict=render.verdict(ep.ok, ep.target), missed=render.hooks(missed))
    r = ex.model.ask(Call(messages(prompt), params(), Reader(schema=HookLessons))).output
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
            for s, nxt in zip(ep.steps, ep.steps[1:]) if s.exec_error and not nxt.failed]


LEARN = {"model": by_model, "raw": by_trajectory}
