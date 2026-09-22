"""Стадия reflect обновления: эпизод -> дельта; память не меняет. Блок: block(ctx, ep, memory, **extra) -> результат.
Результат None обрывает цепочку. Вызов модели — update.ask(промпт метода, поля, схема, parse, then) с полями
и then отсюда.

Обёртки
    keep                            эпизод как есть: всё решает куратор (DC-RS, MCE)
    seq, when, maybe, on_prev       общие блоки цепочки (update.py)
    rounds(block, n)                при неверном ответе: рефлексия -> счётчики на копии памяти -> новая
                                    попытка с рефлексией, до n раз или до верного ответа (ACE)
    per_step(block, steps)          по шагам траектории; найденное раньше в extra["found"] (SCOPE)
    perspectives(block)             по попытке каждой перспективы (SCOPE K=2)
    best_of(block, n, select)       n кандидатов и выбор (SCOPE Best-of-N); two_fields, one_or_two — выбор из двух
    each_attempt(block)             по каждой попытке группы, список пар (попытка, результат) (TF-GRPO)
    by_label, by_issue              промпт по наличию метки (ACE) или ошибки на шаге (SCOPE)

Уроки и метки записей (ACE стенда, прототип)
    lesson_fields(form, sees)       sees: memory — вся память, used — прочитанное решателем
    Reflection, TypedReflection     уроки строками или типизированные (Lesson: kind, when, text)
    labeled_lessons, free_lessons   ответ схемой или свободным текстом -> дельта; episode — запись для provenance

Диагноз ACE: Diagnosis, diagnosis_fields, diagnosis_delta
Правило на шаг SCOPE: agent_steps, Proposal, rule_fields, Selection, selector_fields, selected_index,
    meaningful, rule_lesson, as_lessons
Групповое преимущество TF-GRPO: partial_group, rollout_fields, summarized, advantage_fields, library_fields,
    nonempty_ops, as_ops
Библиотека EvoLib: rank, insight_needed, insight_fields, with_insight, improving, disputed, compare_fields,
    second_better, finish; log_gain, future_gain — прирост лучшей попытки (IG и Future IG)
Cheatsheet DC: answer_and_sheet, rewritten"""
import math
from dataclasses import replace
from typing import Literal

from pydantic import BaseModel

from . import parse
from .inject import counted, text_of
from .memory import perspective_kind
from .update import Delta, count, maybe, on_prev, seq, snapshot, when  # noqa: F401  общие блоки цепочки

# обёртки


def keep(ctx, ep, memory, **extra):
    return ep


def rounds(inner, n=3, note=lambda d: d.lessons[-1]):
    """inner -> Delta. Счётчики каждого раунда сразу идут в копию памяти: следующую попытку решатель
    делает уже с ними; в итоговой дельте метки всех раундов, уроки последнего."""
    def block(ctx, ep, memory, **extra):
        local, attempt, helpful, harmful, last = snapshot(memory), ep, [], [], None
        for _ in range(n if ep.ok is False else 1):
            d = inner(ctx, attempt, local, **extra)
            if not d:
                break
            last = d
            count(local, d.helpful, d.harmful)
            helpful, harmful = helpful + d.helpful, harmful + d.harmful
            if attempt.ok:
                break
            r = ctx.retry(local, note(d))
            attempt = replace(ep, output=r.output, answer=r.answer, steps=r.steps, truncated=r.truncated, used=r.reported,
                              context=r.context, shown=r.shown, ok=ctx.task.check(r.answer, ep.target), group=[])
            if attempt.ok:
                break
        return last and Delta(lessons=last.lessons, helpful=helpful, harmful=harmful, info=last.info)
    return block


def per_step(inner, steps):
    """steps(ep) -> [(сводка шага, ошибка или None)]; inner вызывается с extra step, error, found."""
    def block(ctx, ep, memory, **extra):
        found = []
        for step, error in steps(ep):
            out = inner(ctx, ep, memory, **{**extra, "step": step, "error": error, "found": found})
            if out is not None:
                found.append(out)
        return found or None
    return block


def perspectives(inner):
    """Попытка в зачёт и попытки остальных перспектив из группы; результаты подряд."""
    def block(ctx, ep, memory, **extra):
        out = []
        for e in [ep, *(g for g in ep.group if g.perspective)]:
            out += inner(ctx, e, memory, **extra) or []
        return out or None
    return block


def best_of(inner, n, select, valid=lambda c, **extra: True, temperature=0.7):
    """n = 1: просто inner. Иначе n кандидатов при temperature, отбор valid, из двух и более
    выбирает select(ctx, ep, memory, candidates=..., **extra) -> индекс или None."""
    if n == 1:
        return inner

    def block(ctx, ep, memory, **extra):
        cands = [c for c in (inner(ctx, ep, memory, **{**extra, "temperature": temperature}) for _ in range(n)) if c]
        cands = [c for c in cands if valid(c, **extra)]
        if len(cands) < 2:
            return cands[0] if cands else None
        i = select(ctx, ep, memory, **{**extra, "candidates": cands})
        return cands[i] if i is not None and 0 <= i < len(cands) else cands[0]
    return block


def each_attempt(inner):
    def block(ctx, ep, memory, **extra):
        return [(g, inner(ctx, g, memory, **extra)) for g in ep.group]
    return block


def two_fields(ctx, ep, memory, candidates, **extra):
    """Два кандидата-дельты для выбора: a и b."""
    return dict(a=candidates[0].shown(), b=candidates[1].shown())


def one_or_two(text):
    """Ответ «1» или «2» -> индекс; без ответа первый."""
    return 1 if (text or "1").strip().startswith("2") else 0


def by_label(labeled, unlabeled):
    return lambda ep, memory, **extra: labeled if ep.target else unlabeled


def by_issue(on_error, by_perspective, default):
    """Промпт шага: с ошибкой — on_error, иначе промпт перспективы попытки (без неё — default)."""
    return lambda ep, memory, error=None, **extra: on_error if error else by_perspective[ep.perspective or default]

# уроки и метки записей


Typed = Literal["constraint", "procedure", "insight"]


class Reflection(BaseModel):
    lessons: list[str]
    helpful: list[str] = []
    harmful: list[str] = []


class Lesson(BaseModel):
    kind: Typed
    when: str          # одна строка: когда применять
    text: str

    def __str__(self):
        return f"{self.kind}, when {self.when}: {self.text}"


class TypedReflection(BaseModel):
    helpful: list[str] = []
    harmful: list[str] = []
    lessons: list[Lesson] = []


def lesson_fields(form, sees="memory"):
    def fields(ctx, ep, memory, **extra):
        if sees == "used":
            seen = dict(used="\n".join(f"[{i}] {memory.get(i).text}" for i in ep.used if memory.get(i)) or "(none)")
        else:
            seen = dict(memory=memory.text() or "(empty)")
        return dict(question=ep.question, output=ep.output, verdict=ep.verdict(), form=form, **seen)
    return fields


def provenance(ep):
    return dict(text=f"{ep.verdict()}: {ep.answer}", when=ep.question[:80])


def labeled_lessons(episode=False):
    """Ответ схемой -> уроки и метки. episode: дельта с записью об эпизоде есть всегда, даже без ответа."""
    def then(r, ctx, ep, memory, **extra):
        if not r and not episode:
            return None
        return Delta(lessons=r.lessons if r else [], helpful=r.helpful if r else [], harmful=r.harmful if r else [],
                     episode=provenance(ep) if episode else {})
    return then


def free_lessons(episode=False):
    """Свободный текст -> один урок; куратор разбирает его сам."""
    def then(text, ctx, ep, memory, **extra):
        if not text and not episode:
            return None
        return Delta(lessons=[text] if text else [], episode=provenance(ep) if episode else {})
    return then

# диагноз ACE


class Tag(BaseModel):
    id: str
    tag: str


class Diagnosis(BaseModel):
    reasoning: str
    error_identification: str
    root_cause_analysis: str
    correct_approach: str
    key_insight: str
    bullet_tags: list[Tag] = []


def diagnosis_fields(ctx, ep, memory, **extra):
    """Позиционные поля рефлектора ACE; без метки нет верного ответа."""
    used = [counted(memory.get(i)) for i in ep.used if memory.get(i)]
    bullets = "\n".join(used) if ep.used else "(No bullets used by generator)"
    feedback = "Predicted answer matches ground truth" if ep.ok else "Predicted answer does not match ground truth"
    if ep.target:
        return ep.question, ep.output, ep.answer, ep.target, feedback, bullets
    return ep.question, ep.output, ep.answer, feedback, bullets


def diagnosis_delta(d, ctx, ep, memory, **extra):
    """update_bullet_counts: метки helpful и harmful идут в счётчики, neutral не считается."""
    if not d:
        return None
    return Delta(lessons=[d.model_dump_json(indent=2)], helpful=[t.id for t in d.bullet_tags if t.tag == "helpful"],
                 harmful=[t.id for t in d.bullet_tags if t.tag == "harmful"], info=dict(question=ep.question, labeled=bool(ep.target)))

# правило на шаг SCOPE


class Proposal(BaseModel):
    update_text: str = ""
    rationale: str = ""
    confidence: str = "medium"


class Selection(BaseModel):
    selected_index: int = 0


def step_summary(output="", tools="", observations=""):
    """Сводка шага, обрезанная как в апстриме по умолчанию (truncate_context=True)."""
    cut = lambda s, n: s[:n] + "..." if len(s) > n else s
    parts = [f"Model output: {cut(output, 200)}" if output else "", f"Tool calls: {cut(tools, 150)}" if tools else "",
             f"Observations: {cut(observations, 150)}" if observations else ""]
    return "\n".join(p for p in parts if p) or "(no step details)"


def agent_steps(ep):
    """Шаги агента: вызовы инструментов, затем итоговый ответ. У шага сводка и ошибка (тип, сообщение) или None."""
    out = []
    for name, args, result in ep.steps:
        failed = "Traceback" in result or result.startswith("Error")
        out.append((step_summary(tools=f"{name} {args}", observations=result), ("ToolError", result[-500:]) if failed else None))
    error = None
    if ep.ok is False:
        error = ("IncorrectAnswer", f"Incorrect answer. Model answered '{ep.answer}'" + (f", expected '{ep.target}'." if ep.target else "."))
    elif ep.truncated:
        error = ("Truncated", "The output was cut at the token limit before the final answer.")
    seen = "" if ep.ok is None else f"Answer {'correct' if ep.ok else 'incorrect'}"
    out.append((step_summary(ep.output, observations=seen), error))
    return out


def agent_context(ctx, ep):
    return dict(agent_name=f"{ctx.task.name}_agent", agent_role=ctx.task.system, task=ep.question,
                current_system_prompt=f"{ctx.task.system}\n\n{ep.context}".strip())


def rule_fields(ctx, ep, memory, step, error, found, **extra):
    """Уже действующие правила: tactical перспективы и найденные раньше в этой задаче."""
    rules = [r.text for r in memory.of(perspective_kind("tactical", ep.perspective))] + [g["text"] for g in found]
    fields = dict(agent_context(ctx, ep), last_step_summary=step, applied_rules="\n".join(f"- {r}" for r in rules) or "(none)")
    return dict(fields, error_type=error[0], error_message=error[1]) if error else fields


def selector_fields(ctx, ep, memory, step, error, candidates, **extra):
    text = "".join(f"\n[Candidate {i}]\nUpdate: {c.update_text}\nRationale: {c.rationale}\nConfidence: {c.confidence}\n"
                   for i, c in enumerate(candidates))
    details = f"Error Type: {error[0]}\nError Message: {error[1]}\n\nLast Step:\n{step}" if error else f"Step Details:\n{step}"
    return dict(agent_context(ctx, ep), issue_type="error" if error else "quality", issue_details=details, candidates=text)


def selected_index(s):
    return s.selected_index if s else None


def meaningful(c, error=None, **extra):
    """В Best-of-N без ошибки пустые и «no improvement needed» кандидаты отбрасываются."""
    return bool(error) or bool(c.update_text.strip()) and c.update_text.strip().lower() not in ("no improvement needed", "none")


def rule_lesson(levels):
    """Кандидат -> урок с перспективой и численной confidence по метке (levels: low/medium/high -> число)."""
    def block(ctx, ep, memory, prev, **extra):
        if not prev.update_text:
            return None
        return dict(perspective=ep.perspective, text=prev.update_text, rationale=prev.rationale,
                    confidence=levels.get(prev.confidence.lower(), 0.5))
    return block


def as_lessons(ctx, ep, memory, prev, **extra):
    return Delta(lessons=prev)

# групповое преимущество TF-GRPO


def partial(rollouts, labeled):
    """С меткой в работу идут только группы, где верна часть попыток."""
    if not labeled:
        return bool(rollouts)
    mean = sum(bool(g.ok) for g in rollouts) / len(rollouts) if rollouts else 0
    return 0 < mean < 1


def partial_group(ctx, ep, memory, **extra):
    return partial(ep.group, bool(ep.target))


def answer_or_redacted(ep):
    return ep.target or "[REDACTED]"


def rollout_fields(ctx, g, memory, **extra):
    return dict(question=g.question, trajectory=g.output, answer=answer_or_redacted(g), critique="[No critique provided]")


def summarized(ctx, ep, memory, prev, **extra):
    """Пары (попытка, сводка) без пустых сводок; группа снова должна быть верна частично."""
    kept = [(g, s) for g, s in prev if s]
    return kept if partial([g for g, _ in kept], bool(ep.target)) else None


def advantage_fields(ctx, ep, memory, prev, **extra):
    return dict(question=ep.question, answer=answer_or_redacted(ep), trajectories="\n\n".join(
        f"Attempt {i + 1} (Reward {float(bool(g.ok)) if ep.target else '[REDACTED]'}):\n{s}" for i, (g, s) in enumerate(prev)))


def library_fields(ctx, ep, memory, prev, **extra):
    return dict(existing_experiences="\n".join(f"[{r.id}]. {r.text}" for r in memory.records) or "None", new_experiences=prev)


def nonempty_ops(text):
    ops = parse.json_block(text)
    return ops if isinstance(ops, list) and ops else None


def as_ops(ctx, ep, memory, prev, **extra):
    return Delta(ops=prev)

# библиотека EvoLib; prev — словарь с попытками, баллами и лучшей b


def rank(eps):
    def block(ctx, ep, memory, **extra):
        attempts = [ep, *ep.group]
        scores = [float(bool(a.ok)) for a in attempts]
        b = max(range(len(attempts)), key=scores.__getitem__)          # первая из лучших
        return dict(attempts=attempts, scores=scores, b=b, ig=log_gain(scores[b], scores, eps), insight="")
    return block


def insight_needed(evaluated):
    """С внешней оценкой insight только при неудаче лучшей попытки."""
    return lambda ctx, ep, memory, prev, **extra: not evaluated or prev["scores"][prev["b"]] < 1


def insight_fields(evaluated):
    def fields(ctx, ep, memory, prev, **extra):
        best = prev["attempts"][prev["b"]]
        return dict(question=ep.question, solution=best.output, evaluation=f"\nEvaluation: {best.verdict()}\n" if evaluated else "")
    return fields


def with_insight(evaluated):
    def then(text, ctx, ep, memory, prev, **extra):
        insight = parse.fenced(text, "insight").strip() or parse.between(text or "", "<insight>", "</insight>")
        insight = "" if insight == "N/A" else insight
        halve = insight and not evaluated                         # без внешней оценки баллы делятся пополам
        return dict(prev, insight=insight, scores=[s * 0.5 for s in prev["scores"]] if halve else prev["scores"])
    return then


def improving(ctx, ep, memory, prev, **extra):
    """Лучшее решение задачи в ctx.state["best"]; улучшение — строго выше по баллу."""
    before = ctx.state.setdefault("best", {}).get(ep.question)
    return dict(prev, before=before, improving=not before or prev["scores"][prev["b"]] > before["score"])


def disputed(evaluated):
    """Не лучше по баллу, но большинство теперь за другой ответ: решает сравнение решений моделью."""
    def test(ctx, ep, memory, prev, **extra):
        best = prev["attempts"][prev["b"]]
        voted = best.answer if best.ok and not evaluated else None
        return not prev["improving"] and voted and prev["before"]["answer"] != voted
    return test


def compare_fields(ctx, ep, memory, prev, **extra):
    return dict(question=ep.question, a=prev["before"]["output"], b=prev["attempts"][prev["b"]].output)


def second_better(text, ctx, ep, memory, prev, **extra):
    return dict(prev, improving="solution 2" in parse.fenced(text, "judgment").lower())


def finish(eps):
    def block(ctx, ep, memory, prev, **extra):
        attempts, scores, b = prev["attempts"], prev["scores"], prev["b"]
        best, up = attempts[b], prev["improving"]
        return Delta(info=dict(question=ep.question, ig=prev["ig"], insight=prev["insight"],
                               fig=future_gain(attempts, scores, b, eps),
                               skills=parse.subtasks(best.output) if up else [],
                               best=dict(score=scores[b], output=best.output, answer=best.answer) if up else None))
    return block


def log_gain(best, scores, eps=0.01):
    """log(best) - log(mean(scores)), оба снизу ограничены eps."""
    return math.log(max(best, eps)) - math.log(max(sum(scores) / len(scores), eps))


def future_gain(attempts, scores, best, eps=0.01):
    """Каждой записи, бывшей в промпте лучшей попытки (с повторами), прирост лучшего балла над средним
    по попыткам без этой записи; если таких попыток нет, записи ничего."""
    out = []
    for rid in attempts[best].shown:
        rest = [s for s, a in zip(scores, attempts) if rid not in a.shown]
        if rest:
            out.append((rid, log_gain(scores[best], rest, eps)))
    return out

# cheatsheet DC


def answer_and_sheet(kind, empty):
    return lambda ctx, ep, memory, **extra: {"QUESTION": ep.question, "MODEL_ANSWER": ep.output,
                                             "PREVIOUS_CHEATSHEET": text_of(memory, kind, empty)}


def rewritten(text, *_, **__):
    """Новый текст целиком; None (нет блока) — старый остаётся."""
    return Delta(lessons=[text]) if text is not None else None
