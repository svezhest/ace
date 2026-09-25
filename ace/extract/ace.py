"""Извлечение ACE: по первой попытке группы уроки и метки записей памяти (labels).

    Reflector   рефлектор стенда: уроки и метки одной схемой; free — свободным текстом, без меток;
                temperature — для кандидатов Best-of-N (ace_stand_bo2)
    Diagnose    рефлектор апстрима (ace/core/reflector.py; промпты ace_reflector*.j2 дословно): диагноз с
                метками пунктов; при неверном ответе до rounds раундов «диагноз -> метки в копию памяти ->
                новая попытка с диагнозом как рефлексией генератора» (ex.retry: стрелка извлечение -> попытки).
                Ответ текстом и разбор, как у апстрима (parse.bullet_tags). Какие пункты решатель использовал —
                регулярка апстрима по его ответу (parse.bullet_ids); ids=named — строка USED (ace_used)."""
import copy

from pydantic import BaseModel

from .. import parse, prompts, render
from ..upstream.ace import ace_input, ace_params
from ..memory.counters import count
from ..model import Call, Reader, messages, params
from . import LABELS, Extraction, Extractor, Labels, scores

# стенд

REFLECT = prompts.load("ace_stand_reflect")
REFLECTOR_SYSTEM = prompts.text("reflector_system")
FREE = prompts.text("reflect_free_form")


class Reflection(BaseModel):
    lessons: list[str]
    helpful: list[str] = []
    harmful: list[str] = []


class Reflector(Extractor):
    def __init__(self, free=False, temperature=0):
        self.free = free
        self.temperature = temperature
        self.gives = frozenset() if free else frozenset({LABELS})

    def __call__(self, ex, group, memory):
        ep = group.episodes[0]
        prompt = REFLECT.fill(question=ep.question, output=ep.output, verdict=render.verdict(ep.ok, ep.target),
                              form=FREE if self.free else "", memory=render.lines(memory.records()) or render.EMPTY)
        call = Call(messages(prompt, render.skilled(REFLECTOR_SYSTEM, ex)), params(self.temperature))
        if self.free:
            text = ex.model.ask(call).output
            return Extraction(group, [text], scores(group)) if text else None
        call.reader = Reader(schema=Reflection)
        r = ex.model.ask(call).output
        if not r:
            return None
        return Extraction(group, r.lessons, scores(group), {LABELS: Labels(r.helpful, r.harmful)})

# апстрим


REFLECTOR_GT = prompts.load("ace_reflector")
REFLECTOR_NOGT = prompts.load("ace_reflector_nogt")
ROUNDS = 3                  # --max_num_rounds апстрима: раундов рефлексии на неверном ответе


def used_line(text):
    """Самоотчёт вместо bullet_ids: последняя строка «USED: r1, r3» в обычном ответе решателя."""
    lines = [line for line in text.splitlines() if line.strip().upper().startswith("USED:")]
    if not lines:
        return []
    listed = lines[-1].split(":", 1)[1]
    return [rid.strip(" []") for rid in listed.split(",")]


def named(ep):
    """id, которые решатель назвал в строке USED; «none» — ни одного."""
    return [i for i in used_line(ep.final) if i and i.lower() != "none"]


def cited(ep):
    """bullet_ids генератора апстрима: регулярка по всему ответу."""
    return parse.bullet_ids(ep.final)


def bullets_used(memory, ids):
    """extract_playbook_bullets апстрима: названные пункты в порядке playbook; без id и без найденных — строки
    апстрима."""
    if not ids:
        return prompts.text("ace_no_bullets")
    found = [r for r in memory.records() if r.id in ids]
    return render.bullets_used(found) if found else prompts.text("ace_bullets_not_found")


def tag_map(tags):
    """Метки рефлектора, как их применяет update_bullet_counts апстрима: id (или bullet) -> tag, при повторе id
    побеждает последняя; не список и не словари — ничего."""
    if not isinstance(tags, list):
        return {}
    out = {}
    for tag in tags:
        if not isinstance(tag, dict):
            continue
        rid = tag.get("id") or tag.get("bullet", "")
        if rid:
            out[rid] = tag.get("tag", "neutral")
    return out


TAGS = Reader(text=parse.bullet_tags)     # _extract_bullet_tags апстрима без json_mode


class Diagnose(Extractor):
    """Рефлектор апстрима: ответ текстом, метки — разбор read (bullet_tags без json_mode, по умолчанию в апстриме),
    урок для куратора — весь ответ рефлектора, как recent_reflection апстрима. Вопрос — question из
    DataProcessor апстрима (ace_input)."""
    gives = frozenset({LABELS})

    def __init__(self, rounds=ROUNDS, read=TAGS, ids=cited):
        self.rounds = rounds
        self.read = read
        self.ids = ids

    def diagnose(self, ex, ep, memory):
        """Поля рефлектора апстрима; без верного ответа — промпт _nogt. -> (ответ текстом, метки)."""
        feedback = prompts.text("ace_environment_feedback", correct=ep.ok)
        fields = dict(question=ace_input(ex.task.name, ep.question)[1], reasoning_trace=ep.output,
                      predicted_answer=ep.answer, environment_feedback=feedback,
                      bullets_used=bullets_used(memory, self.ids(ep)))
        if ep.target:
            prompt = REFLECTOR_GT.fill(**fields, ground_truth=ep.target)
        else:
            prompt = REFLECTOR_NOGT.fill(**fields)
        reply = ex.model.ask(Call(messages(prompt), ace_params(), self.read))
        return reply.raw or "", reply.output

    def __call__(self, ex, group, memory):
        """Метки каждого раунда сразу идут в копию памяти: следующую попытку решатель делает уже с ними.
        В извлечении метки всех раундов и ответ рефлектора последнего раунда."""
        ep = group.episodes[0]
        local = copy.deepcopy(memory)
        current = ep            # попытка, по которой идёт диагноз этого раунда
        labels = Labels()
        # как в апстриме: после диагноза неверного ответа — новая попытка с ним; верная — стоп; последняя новая
        # попытка раундов делается, даже если диагноза по ней уже не будет
        for _ in range(self.rounds if ep.ok is False else 1):
            text, tags = self.diagnose(ex, current, local)
            tags = tag_map(tags)
            helpful = [rid for rid, tag in tags.items() if tag == "helpful"]
            harmful = [rid for rid, tag in tags.items() if tag == "harmful"]
            count(local, helpful, harmful)
            labels.helpful += helpful
            labels.harmful += harmful
            if current.ok:
                break
            current = ex.retry(local, text)
            if current.ok:
                break
        return Extraction(group, [text], scores(group), {LABELS: labels})
