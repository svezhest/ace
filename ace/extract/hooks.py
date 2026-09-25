"""Извлечение хуков по ошибкам: уроки по ошибкам каждой попытки группы и исходы показанных хуков (метки).

    by_model        после вопроса модель выводит уроки по ошибкам попытки (hook_reflect); в память идут уверенные
                    (high), чей trigger дословно есть в тексте ошибки; модели показываются и хуки, которые не помогли
    by_trajectory   без модели, как пары DC: ошибка и следующий вызов, который прошёл"""
from typing import Literal, get_args

from pydantic import BaseModel

from .. import prompts, render
from ..model import Call, Reader, messages, params
from . import LABELS, TRIGGER, Extraction, Extractor, Labels, scores

REFLECT = prompts.load("hook_reflect")
Level = Literal["low", "medium", "high"]
LEVELS = get_args(Level)
ERROR_KIND_CHARS = 60       # trigger хука из траектории, если имени исключения нет


class HookLesson(BaseModel):
    trigger: str
    lesson: str
    confidence: Level


class HookLessons(BaseModel):
    hooks: list[HookLesson] = []


def error_steps(ep):
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
        hooks = []              # (trigger, урок)
        for ep in group.episodes:
            if error_steps(ep):
                hooks += self.learn(ex, ep, memory)
        labels = outcomes(group)
        if not hooks and not labels.helpful and not labels.harmful:
            return None
        return Extraction(group, [t for _, t in hooks], scores(group), {TRIGGER: [t for t, _ in hooks], LABELS: labels})


def missed(ep, memory):
    """Хуки, которые показаны в попытке и не помогли, — по разу, в порядке первого показа."""
    out = []
    for rid, helped in ep.fired:
        hook = memory.get(rid)
        if not helped and hook is not None and hook not in out:
            out.append(hook)
    return out


def confident(hook, level, errors):
    """Урок не ниже level, и его trigger дословно есть в тексте одной из ошибок."""
    trigger = hook.trigger.strip().lower()
    if LEVELS.index(hook.confidence) < LEVELS.index(level) or not trigger:
        return False
    return any(trigger in e for e in errors)


def by_model(ex, ep, memory, level="high"):
    """Уверенные уроки модели, чей trigger есть в тексте одной из ошибок попытки."""
    prompt = REFLECT.fill(question=ep.question, errors=render.failed_steps(error_steps(ep)), output=ep.output,
                          verdict=render.verdict(ep.ok, ep.target), missed=render.hooks(missed(ep, memory)))
    reply = ex.model.ask(Call(messages(prompt), params(), Reader(schema=HookLessons))).output
    errors = [s.result.lower() for s in error_steps(ep)]
    hooks = reply.hooks if reply else []
    return [(h.trigger.strip(), h.lesson.strip()) for h in hooks if confident(h, level, errors)]


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
