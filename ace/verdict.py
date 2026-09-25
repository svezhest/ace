"""Вердикты: что обучение узнаёт о правильности. Масштабы разные и не смешиваются.

Вердикт попытки — verdict(ex, episode, target): ставит episode.ok, а верный ответ кладёт в эпизод только
golden. Обучение видит только эпизод, поэтому метод «без верного ответа» на него не посмотрит.
    golden    ok и верный ответ
    yes_no    только ok
    judge     ok ставит модель-судья по траектории
    none      ничего

Вердикт группы — group_verdict(ex, group): что известно о группе попыток целиком.
    vote      group.vote — самый частый ответ (EvoLib без метки: попытка «верна», если совпала с ним)
    none      ничего
Контраст попыток группы (TF-GRPO) — не вердикт, а извлечение."""
from collections import Counter

from . import prompts
from .model import Call, messages, params

JUDGE = prompts.load("judge")


def golden(ex, episode, target):
    episode.ok = ex.task.check(episode.answer, target)
    episode.target = target


def yes_no(ex, episode, target):
    episode.ok = ex.task.check(episode.answer, target)


def judge(ex, episode, target):
    """Самопроверка с вердиктом в конце; голое число модель ставит наугад (14/20 против 17/20). Вне обучения
    вердикт никто не читает (в зачёт — проверка задачи), и судья не зовётся."""
    if not ex.training:
        return
    prompt = JUDGE.fill(question=episode.question, output=episode.output)
    word = judged(ex.model.ask(Call(messages(prompt, prompts.text("judge_system")), params())).output or "")
    episode.ok = word == "correct"


def judged(text):
    """Слово вердикта из последней строки «VERDICT: ...»: correct | wrong; иначе (incorrect, not correct, нет
    строки) — None. Звёздочки Markdown и знаки после слова не мешают."""
    for line in reversed(text.splitlines()):
        line = line.replace("*", "").strip()
        if line.upper().startswith("VERDICT:"):
            words = line[len("VERDICT:"):].split()
            word = words[0].strip(".,;:!—-").lower() if words else ""
            return word if word in ("correct", "wrong") else None
    return None


def none(*_):
    """Нет вердикта: и для попытки, и для группы."""


def vote(ex, group):
    group.vote = majority(e.answer for e in group.episodes)


def majority(answers):
    """Самый частый непустой ответ; при равенстве первый встреченный; без ответов — пустая строка."""
    votes = Counter(a for a in answers if a)
    return votes.most_common(1)[0][0] if votes else ""
