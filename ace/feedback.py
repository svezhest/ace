"""Элемент 3. Сигнал: что после попытки возвращается в систему.

Обновление видит только Episode, а не пример из датасета. Верный ответ попадает в эпизод
лишь при verdict = golden; при judge вердикт ставит сама модель; при majority попытка верна,
если её ответ совпал с самым частым ответом группы (EvoLib без метки); при none вердикта нет.
Что решатель прочёл (usage):
    env   чтения через инструменты инжекта: факт, записанный средой
    self  самоотчёт в ответе решателя (bullet_ids): слова модели, не факт
    none  неизвестно
"""
from collections import Counter
from dataclasses import dataclass, field

JUDGE = """Check the solution below. Recompute the key quantities yourself and compare with the solution's final answer.
End with one line: VERDICT: correct  or  VERDICT: wrong

## Task
{question}

## Solution
{output}"""


@dataclass
class Episode:
    question: str
    output: str                 # вся траектория текстом
    answer: str
    steps: list                 # вызовы инструментов: (имя, аргументы, результат)
    truncated: bool
    context: str = ""           # что из памяти решатель видел в промпте
    shown: list = field(default_factory=list)   # id записей в промпте
    used: list = field(default_factory=list)    # id записей, которые решатель прочёл (по usage)
    ok: bool = None             # вердикт; None, если его нет
    target: str = ""            # верный ответ, только при golden
    group: list = field(default_factory=list)   # остальные попытки того же вопроса, тоже Episode
    perspective: str = ""       # чья часть памяти была у решателя (SCOPE K=2)

    def verdict(self):
        if self.ok is None:
            return "unknown"
        if self.ok:
            return "correct"
        return f"wrong, correct answer: {self.target}" if self.target else "wrong"


@dataclass
class Feedback:
    verdict: str = "golden"     # golden | yes_no | judge | majority | none
    usage: str = "none"         # env | self | none

    def observe(self, model, attempt, group=()):
        ep = Episode(attempt.question, attempt.output, attempt.answer, attempt.steps, attempt.truncated,
                     attempt.context, attempt.shown, perspective=attempt.perspective)
        ep.used = {"env": attempt.reads, "self": attempt.reported}.get(self.usage, [])
        if self.verdict in ("golden", "yes_no"):
            ep.ok = attempt.correct
        if self.verdict == "golden":
            ep.target = attempt.target
        if self.verdict == "judge":
            ep.ok = judge(model, attempt)
        ep.group = [self.observe(model, a) for a in group]
        if self.verdict == "majority":
            votes = Counter(e.answer for e in [ep, *ep.group] if e.answer)
            top = votes.most_common(1)[0][0] if votes else None
            for e in [ep, *ep.group]:
                e.ok = bool(top) and e.answer == top
        return ep


def judge(model, attempt):
    """Самопроверка с вердиктом в конце; голое число модель ставит наугад (14/20 против 17/20)."""
    s = model.one("You are a strict grader.", JUDGE.format(question=attempt.question, output=attempt.output)).output or ""
    return "VERDICT:" in s and "correct" in s.split("VERDICT:")[-1].lower()
