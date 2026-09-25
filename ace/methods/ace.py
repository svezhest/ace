"""ACE (Agentic Context Engineering): вариант стенда и вариант апстрима.

ace — стенд, основа цепочки абляций:
    память      пункты-уроки со счётчиками; куратор отвечает операциями ADD / UPDATE одной схемой (UPDATE —
                новый пункт на месте старого, счётчики с нуля); отсев вредных
    показ       все пункты «[id] текст»
    извлечение  рефлектор: уроки и метки пунктов одной схемой
    вердикт     верный ответ
ace_text — рефлексия свободным текстом: меток нет, поэтому и память без счётчиков и отсева (иначе стык не
    соберётся: памяти нужны labels).
ace_rewrite — куратор переписывает всю память, пункт на строку: старые пункты уходят со счётчиками, новые — с нуля.

ace_exact — как в апстриме (ace/ace/ace.py, core/, playbook_utils.py; промпты ace_*.j2 дословно):
    память      playbook из 7 разделов (контейнеры с общей нумерацией); пункты только добавляются: куратор
                (последняя рефлексия, вопрос, бюджет токенов, статистика) отвечает ADD с разделом; счётчики
    показ       весь playbook по разделам, строка «[id] helpful=X harmful=Y :: текст», и просьба назвать
                использованные пункты строкой USED (вместо bullet_ids)
    извлечение  диагноз с метками, при неверном ответе до 3 раундов с новой попыткой (extract/ace.py)
    Решение после куратора в апстриме только для отчёта: не делаем.
ace_exact_dedup — после куратора похожие пункты сливаются моделью (BulletpointAnalyzer; в апстриме выключен).
"""
from typing import Literal

from pydantic import BaseModel

from .. import embed, parse, prompts, render
from ..extract import LABELS
from ..extract.ace import Diagnose, Reflector
from ..learner import Learner, swap
from ..memory import HARMFUL, HELPFUL, Lessons, Operation, Sections
from ..show import Whole
from ..wrap import skilled

# ace

CURATE = {n: prompts.load(f"ace_stand_curate_{n}") for n in ("json", "rewrite")}
CURATOR = prompts.text("curator_system")
PRUNE_HARMFUL = 3           # пункт уходит, когда вредных меток не меньше и больше, чем полезных


class Op(BaseModel):
    op: Literal["ADD", "UPDATE"]
    text: str
    id: str = ""


class Ops(BaseModel):
    ops: list[Op]


def curator_prompt(template, memory, x):
    return template.fill(lessons=render.lessons(x.lessons), memory=render.lines(memory.records()) or render.EMPTY)


def curate_ops(ex, memory, x):
    """Все операции одной схемой; UPDATE несуществующего id пропускается."""
    r = ex.model.run(skilled(CURATOR, ex), curator_prompt(CURATE["json"], memory, x), output=Ops).output
    memory.apply([dict(operation=o.op, id=o.id, content=o.text) for o in (r.ops if r else [])])


def curate_rewrite(ex, memory, x):
    """Вся память заново: промпт просит пункт на строку, каждая непустая строка — новая запись; пустой
    ответ — память как была."""
    new = ex.model.run(skilled(CURATOR, ex), curator_prompt(CURATE["rewrite"], memory, x)).output
    if new and new.strip():
        memory.replace([line.strip() for line in new.splitlines() if line.strip()])


class Playbook(Lessons):
    """Пункты стенда: метки рефлектора -> журнал исходов, уроки -> куратор, затем отсев вредных.
    prune=None — без отсева; тогда и метки не нужны."""
    def __init__(self, curator=curate_ops, prune=PRUNE_HARMFUL):
        super().__init__("bullet", ops=Operation.ADD | Operation.UPDATE)
        self.curator, self.prune_at = curator, prune
        self.requires = frozenset({LABELS}) if prune else frozenset()

    def learn(self, ex, extractions):
        for x in extractions:
            if LABELS in x.extras:
                self.count(x.extras[LABELS].helpful, x.extras[LABELS].harmful)
            if x.lessons:
                self.curator(ex, self, x)
        if self.prune_at:
            self.prune(lambda r: r.harmful >= self.prune_at and r.harmful > r.helpful)


ace = Learner("ace", memory=Playbook(), extract=Reflector())
ace_text = swap(ace, "ace_text", extract=Reflector(free=True), memory=Playbook(prune=None))
ace_rewrite = swap(ace, "ace_rewrite", memory=Playbook(curate_rewrite))

# ace_exact

P = {n: prompts.load(f"ace_{n}") for n in ("curator", "curator_nogt", "merge")}
SECTIONS = ["STRATEGIES & INSIGHTS", "FORMULAS & CALCULATIONS", "CODE SNIPPETS & TEMPLATES", "COMMON MISTAKES TO AVOID",
            "PROBLEM-SOLVING HEURISTICS", "CONTEXT CLUES & INDICATORS", "OTHERS"]
OTHERS = "others"
TOKEN_BUDGET = 80000
HIGH_HELPFUL, HIGH_HARMFUL = 5, 2   # пункт «high performing»: helpful больше и harmful меньше этих
DEDUP = 0.85                # порог косинуса слияния; у апстрима 0.90 под all-mpnet, у BGE-M3 косинусы ниже
MERGE_TEMPERATURE = 0.3


def slug(title):
    """Имя раздела из заголовка апстрима."""
    return title.lower().strip().replace(" ", "_").replace("&", "and")


TITLES = {slug(s): s for s in SECTIONS}


class Addition(BaseModel):
    type: str = "ADD"
    section: str = "others"
    content: str


class Curation(BaseModel):
    reasoning: str
    operations: list[Addition] = []


def layout(records, playbook):
    """Весь playbook по разделам, пустые разделы тоже (как в апстриме)."""
    return render.titled([(TITLES[n], s.records()) for n, s in playbook.sections.items()], render.counted)


class SectionedPlaybook(Sections):
    requires = frozenset({LABELS})

    def __init__(self, dedup=None):
        super().__init__(list(TITLES), "bullet", ops=Operation.ADD)
        self.dedup = dedup

    def learn(self, ex, extractions):
        for x in extractions:
            self.count(x.extras[LABELS].helpful, x.extras[LABELS].harmful)
            self.curate(ex, x)
        if self.dedup:
            self.merge_similar(ex)

    def section(self, name):
        return slug(name) if slug(name) in self.sections else OTHERS

    def curate(self, ex, x):
        fields = dict(token_budget=TOKEN_BUDGET, current_step=ex.i + 1, total_samples=ex.total,
                      playbook_stats=render.stats(self.stats()), recent_reflection=x.lessons[-1],
                      current_playbook=layout(None, self), question_context=x.group.question)
        r = ex.model.run("", P["curator" if x.group.target else "curator_nogt"].fill(fields), output=Curation).output
        for op in (r.operations if r else []):
            if op.type == "ADD":            # apply_curator_operations апстрима применяет только ADD
                self.add(op.content, self.section(op.section))

    def stats(self):
        """get_playbook_stats апстрима."""
        stats = dict(total_bullets=0, high_performing=0, problematic=0, unused=0, by_section={})
        for name, section in self.sections.items():
            for r in section.records():
                stats["total_bullets"] += 1
                if r.helpful > HIGH_HELPFUL and r.harmful < HIGH_HARMFUL:
                    stats["high_performing"] += 1
                elif r.harmful >= r.helpful and r.harmful > 0:
                    stats["problematic"] += 1
                elif r.helpful + r.harmful == 0:
                    stats["unused"] += 1
                sec = stats["by_section"].setdefault(TITLES[name], dict(count=0, helpful=0, harmful=0))
                sec["count"] += 1
                sec["helpful"] += r.helpful
                sec["harmful"] += r.harmful
        return stats

    def merge_similar(self, ex):
        """BulletpointAnalyzer: к пункту i все следующие с косинусом >= DEDUP, уже попавшие в группу
        пропускаются; группа сливается моделью в новый пункт на месте первого со счётчиками, которые вернула
        модель (сумма по группе); если ответ не разобрался, остаётся первый. Остальные уходят."""
        recs = self.records()
        if len(recs) < 2:
            return
        vecs = embed.embed([r.text for r in recs])
        sims, seen = vecs @ vecs.T, set()
        for i in range(len(recs)):
            if i in seen:
                continue
            group = [i] + [j for j in range(i + 1, len(recs)) if sims[i][j] >= DEDUP]
            if len(group) == 1:
                continue
            seen.update(group)
            merged = self.merge(ex, [recs[j] for j in group])
            if merged:
                text, helpful, harmful = merged
                self.update(recs[i].id, text, outcomes=[HELPFUL] * helpful + [HARMFUL] * harmful)
            for j in group[1:]:
                self.delete(recs[j].id)

    def merge(self, ex, group):
        first = group[0]
        helpful, harmful = sum(r.helpful for r in group), sum(r.harmful for r in group)
        out = ex.model.one("", P["merge"].fill(bullets=render.merge_group(group), id=first.id, helpful=helpful,
                                               harmful=harmful), temperature=MERGE_TEMPERATURE).output
        return parse.counted_line(first.id)(out)


PLAYBOOK = Whole(layout=layout, after="\n\n" + prompts.text("solver_used"))

ace_exact = Learner("ace_exact", memory=SectionedPlaybook(), show=PLAYBOOK, extract=Diagnose())
ace_exact_dedup = swap(ace_exact, "ace_exact_dedup", memory=SectionedPlaybook(dedup=DEDUP))
