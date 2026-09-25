"""Извлечение ACE: по первой попытке группы уроки и метки записей памяти (labels).

    Reflector   рефлектор стенда: уроки и метки одной схемой; free — свободным текстом, без меток
    Diagnose    рефлектор апстрима (ace/core/reflector.py; промпты ace_reflector*.j2 дословно): диагноз с
                метками пунктов; при неверном ответе до rounds раундов «диагноз -> метки в копию памяти ->
                новая попытка с диагнозом как заметкой» (ex.retry: стрелка извлечение -> попытки).
                Какие пункты решатель использовал, он называет сам строкой USED (вместо bullet_ids)."""
import copy

from pydantic import BaseModel

from .. import prompts, render
from . import LABELS, Extraction, Extractor, Labels, scores

# стенд

REFLECT = prompts.load("ace_stand_reflect")
REFLECTOR = prompts.text("reflector_system")
FREE = prompts.text("reflect_free_form")


class Reflection(BaseModel):
    lessons: list[str]
    helpful: list[str] = []
    harmful: list[str] = []


class Reflector(Extractor):
    def __init__(self, free=False):
        self.free = free
        self.gives = frozenset() if free else frozenset({LABELS})

    def __call__(self, ex, group, memory):
        ep = group.episodes[0]
        prompt = REFLECT.fill(question=ep.question, output=ep.output, verdict=render.verdict(ep.ok, ep.target),
                              form=FREE if self.free else "", memory=render.lines(memory.records()) or render.EMPTY)
        if self.free:
            text = ex.model.run(REFLECTOR, prompt).output
            return Extraction(group, [text], scores(group)) if text else None
        r = ex.model.run(REFLECTOR, prompt, output=Reflection).output
        if not r:
            return None
        return Extraction(group, r.lessons, scores(group), {LABELS: Labels(r.helpful, r.harmful)})

# апстрим


P = {n: prompts.load(f"ace_{n}") for n in ("reflector", "reflector_nogt")}
ROUNDS = 3


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


def used_line(text):
    """Самоотчёт вместо bullet_ids: последняя строка «USED: r1, r3» в обычном ответе решателя."""
    lines = [l for l in text.splitlines() if l.strip().upper().startswith("USED:")]
    return [i.strip(" []") for i in lines[-1].split(":", 1)[1].split(",")] if lines else []


def reported(ep, memory):
    """id из строки USED, которые есть в памяти."""
    return [i for i in used_line(ep.final) if memory.get(i)]


class Diagnose(Extractor):
    gives = frozenset({LABELS})

    def __init__(self, rounds=ROUNDS):
        self.rounds = rounds

    def diagnose(self, ex, ep, used, memory):
        """Поля рефлектора апстрима; без верного ответа — промпт _nogt."""
        bullets = [render.counted(memory.get(i)) for i in used if memory.get(i)]
        fields = dict(question=ep.question, reasoning_trace=ep.output, predicted_answer=ep.answer,
                      environment_feedback=prompts.text("ace_environment_feedback", correct=ep.ok),
                      bullets_used="\n".join(bullets) if used else prompts.text("ace_no_bullets"))
        if ep.target:
            fields["ground_truth"] = ep.target
        return ex.model.run("", P["reflector" if ep.target else "reflector_nogt"].fill(fields), output=Diagnosis).output

    def __call__(self, ex, group, memory):
        """Метки каждого раунда сразу идут в копию памяти: следующую попытку решатель делает уже с ними.
        В извлечении метки всех раундов и диагноз последнего."""
        ep = group.episodes[0]
        local, attempt, used = copy.deepcopy(memory), ep, reported(ep, memory)
        labels, last = Labels(), None
        for _ in range(self.rounds if ep.ok is False else 1):
            d = self.diagnose(ex, attempt, used, local)
            if not d:
                break
            last = d
            helpful = [t.id for t in d.bullet_tags if t.tag == "helpful"]
            harmful = [t.id for t in d.bullet_tags if t.tag == "harmful"]
            local.count(helpful, harmful)
            labels.helpful += helpful
            labels.harmful += harmful
            if attempt.ok:
                break
            attempt = ex.retry(local, d.model_dump_json(indent=2))
            used = reported(attempt, local)
            if attempt.ok:
                break
        if last is None:
            return None
        return Extraction(group, [last.model_dump_json(indent=2)], scores(group), {LABELS: labels})
