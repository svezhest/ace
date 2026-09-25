"""Память ACE: пункты стенда (Playbook) и playbook апстрима (SectionedPlaybook).

Playbook — стенд: пункты-уроки со счётчиками; куратор отвечает операциями ADD / UPDATE одной схемой (UPDATE —
    новый пункт на месте старого, счётчики с нуля) или переписывает всю память (пункт на строку); отсев вредных.
CappedPlaybook — пункты стенда с пределом SCOPE вместо отсева (ace_stand_opt).
SectionedPlaybook — playbook апстрима (ace/ace/ace.py, core/curator.py, playbook_utils.py; промпты ace_*.j2 дословно):
    7 разделов, id «calc-00001» (слаг раздела и общий номер); куратор отвечает текстом, из JSON берутся только ADD;
    dedup — похожие пункты сливает модель (BulletpointAnalyzer; в апстриме выключен)."""
from typing import Literal

from pydantic import BaseModel

from .. import embed, parse, prompts, render
from ..extract import LABELS
from ..model import TEXT, Call, Reader, messages, params
from ..upstream.ace import ace_input, ace_params
from . import Ids, Lessons, Sections
from .counters import HARMFUL, HELPFUL, Counted, count, prune_harmful
from .scope import CAP, compress, optimize, target_count

# стенд

CURATE_JSON = prompts.load("ace_stand_curate_json")
CURATE_REWRITE = prompts.load("ace_stand_curate_rewrite")
CURATOR = prompts.text("curator_system")
PRUNE_HARMFUL = 3           # пункт уходит, когда вредных меток не меньше и больше, чем полезных


class Op(BaseModel):
    op: Literal["ADD", "UPDATE"]
    text: str
    id: str = ""


class Ops(BaseModel):
    ops: list[Op]


def ask_curator(ex, template, memory, x, reader=TEXT):
    """Куратор стенда: уроки дельты и память строками, системный промпт — с навыком меты."""
    prompt = template.fill(lessons=render.bullets(x.lessons), memory=render.lines(memory.records()) or render.EMPTY)
    return ex.model.ask(Call(messages(prompt, render.skilled(CURATOR, ex)), params(), reader)).output


def curate_ops(ex, memory, x):
    """Все операции одной схемой; UPDATE несуществующего id пропускается."""
    reply = ask_curator(ex, CURATE_JSON, memory, x, Reader(schema=Ops))
    ops = reply.ops if reply else []
    memory.apply([dict(operation=o.op, id=o.id, content=o.text) for o in ops])


def curate_rewrite(ex, memory, x):
    """Вся память заново: промпт просит пункт на строку, каждая непустая строка — новая запись; пустой
    ответ — память как была."""
    new = ask_curator(ex, CURATE_REWRITE, memory, x)
    if new and new.strip():
        memory.replace([line.strip() for line in new.splitlines() if line.strip()])


class Playbook(Lessons):
    """Пункты стенда: метки рефлектора -> журнал исходов, уроки -> куратор, затем отсев вредных.
    prune=None — без отсева; тогда и метки не нужны."""
    def __init__(self, curator=curate_ops, prune=PRUNE_HARMFUL):
        super().__init__("bullet", Counted)
        self.curator, self.prune_at = curator, prune
        self.requires = frozenset({LABELS}) if prune else frozenset()

    def learn(self, ex, extractions):
        for x in extractions:
            if LABELS in x.extras:
                count(self, x.extras[LABELS].helpful, x.extras[LABELS].harmful)
            if x.lessons:
                self.curator(ex, self, x)
        if self.prune_at:
            prune_harmful(self, self.prune_at)


class CappedPlaybook(Playbook):
    """Пункты стенда с пределом SCOPE вместо отсева: сверх cap пунктов оптимизатор правил сжимает до target,
    остаток обрезается до cap; нетронутые пункты остаются со своими счётчиками, исправленные и слитые — новые."""
    def __init__(self, cap=CAP):
        super().__init__(prune=None)
        self.cap = cap
        self.target = target_count(cap)
        self.optimizer = optimize

    def learn(self, ex, extractions):
        super().learn(ex, extractions)
        self.items = compress(ex.model, self.items, self.optimizer, self.target, self.cap, self.new_record)

    def new_record(self, rule):
        """Исправленное или слитое оптимизатором правило — новый пункт со счётчиками с нуля."""
        return self.record(self.ids.next(), rule["rule"])

# апстрим


CURATOR_GT = prompts.load("ace_curator")
CURATOR_NOGT = prompts.load("ace_curator_nogt")
MERGE = prompts.load("ace_merge")
SECTIONS = prompts.text("ace_sections").splitlines()
OTHERS = "others"
GENERAL = "general"         # раздел, которого нет: пункт встаёт в начало OTHERS
SLUGS = {"financial_strategies_and_insights": "fin", "formulas_and_calculations": "calc", "code_snippets_and_templates": "code",
         "common_mistakes_to_avoid": "err", "problem_solving_heuristics": "prob", "context_clues_and_indicators": "ctx",
         "others": "misc", "meta_strategies": "meta"}
TOKEN_BUDGET = 80000
HIGH_HELPFUL = 5            # пункт «high performing»: helpful больше и harmful меньше этих
HIGH_HARMFUL = 2
DEDUP = 0.85                # порог косинуса слияния; у апстрима 0.90 под all-mpnet, у BGE-M3 косинусы ниже
MERGE_TEMPERATURE = 0.3
OPERATIONS = Reader(text=parse.ace_operations)      # _extract_and_validate_operations куратора апстрима


def question_context(task, text):
    """Question Context куратора — context из DataProcessor апстрима (отдельной функцией ради сверки с апстримом)."""
    return ace_input(task, text)[0]


def section_key(name):
    """Имя раздела из заголовка или из операции куратора, как в apply_curator_operations (без strip: у операции
    лишний пробел даёт другое имя)."""
    return name.lower().replace(" ", "_").replace("&", "and")


def section_slug(name):
    """get_section_slug апстрима (utils.py:52): слаг из словаря или первые буквы слов (одно слово — 4 буквы)."""
    clean = section_key(name.strip())
    if clean in SLUGS:
        return SLUGS[clean]
    words = clean.split("_")
    return words[0][:4] if len(words) == 1 else "".join(w[0] for w in words[:5])


TITLES = {section_key(s): s for s in SECTIONS}


class SlugIds(Ids):
    """Id пункта апстрима: слаг раздела и общий номер, «calc-00001» (apply_curator_operations)."""
    slug = "misc"

    def next(self):
        self.n += 1
        return f"{self.slug}-{self.n:05d}"

    def order(self, id):
        return int(id.rsplit("-", 1)[1])


def layout(playbook):
    """Весь playbook текстом, как его ведёт апстрим."""
    return render.ace_playbook([(TITLES[n], s.records()) for n, s in playbook.sections.items()])


class SectionedPlaybook(Sections):
    """Playbook апстрима: 7 разделов, общий счётчик id со слагом раздела. Порядок пунктов — как в тексте апстрима:
    по разделам, внутри раздела по добавлению; пункт раздела general — в начало OTHERS."""
    requires = frozenset({LABELS})

    def __init__(self, dedup=None, read=OPERATIONS):
        super().__init__(list(TITLES), "bullet", Counted, SlugIds())
        self.dedup, self.read = dedup, read

    def records(self):
        return [r for s in self.sections.values() for r in s.items]

    def key(self):
        """Кэш val: решатель видит в playbook и счётчики пунктов (layout), не только текст."""
        return tuple((r.id, r.text, r.helpful, r.harmful) for r in self.records())

    def learn(self, ex, extractions):
        for x in extractions:
            count(self, x.extras[LABELS].helpful, x.extras[LABELS].harmful)
            self.curate(ex, x)
        if self.dedup:
            self.merge_similar(ex)

    def curate(self, ex, x):
        """Curator.curate апстрима: ответ текстом, разбор и проверка как у апстрима (ошибка — ответ пропускается
        целиком); применяются только ADD, UPDATE / DELETE / MERGE апстрим молча пропускает."""
        fields = dict(token_budget=TOKEN_BUDGET, current_step=ex.i + 1, total_samples=ex.total,
                      playbook_stats=render.pretty_json(self.stats()), recent_reflection=x.lessons[-1],
                      current_playbook=layout(self), question_context=question_context(ex.task.name, x.group.question))
        template = CURATOR_GT if x.group.target else CURATOR_NOGT
        prompt = template.fill(**fields)
        self.apply(ex.model.ask(Call(messages(prompt), ace_params(), self.read)).output or [])

    def apply(self, ops):
        """apply_curator_operations апстрима: только ADD; раздел без strip, неизвестный — OTHERS, general — в начало
        OTHERS; id — слаг раздела и общий номер. Ошибка на любой операции — не применяется ни одна."""
        adds = []
        try:
            for op in ops:
                if op["type"] == "ADD":
                    # f-строка, как в апстриме: содержимое любого типа — строкой
                    adds.append((self.place(op.get("section", GENERAL)), f"{op.get('content', '')}"))
        except Exception:
            return
        top = 0
        for (name, slug), text in adds:
            self.ids.slug = slug
            if name == GENERAL:     # раздела general нет: пункт встаёт сразу под заголовок OTHERS
                self.add(text, OTHERS)
                items = self.sections[OTHERS].items
                items.insert(top, items.pop())
                top += 1
            else:
                self.add(text, name)

    def place(self, section):
        """(раздел, слаг) нового пункта: неизвестный раздел — others, кроме general (слаг gene, место — начало
        OTHERS)."""
        name = section_key(section)
        if name not in self.sections and name != GENERAL:
            name = OTHERS
        return name, section_slug(name)

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
        модель (сумма по группе), остальные уходят; если ответ не разобрался, группа остаётся целиком, как у
        апстрима (индексы не попадают в processed_indices)."""
        recs = self.records()
        if len(recs) < 2:
            return
        vecs = embed.embed([r.text for r in recs])
        sims = vecs @ vecs.T
        seen = set()
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
                self.ids.slug = recs[i].id.rsplit("-", 1)[0]
                self.update(recs[i].id, text, outcomes=[HELPFUL] * helpful + [HARMFUL] * harmful)
                for j in group[1:]:
                    self.delete(recs[j].id)

    def merge(self, ex, group):
        first = group[0]
        helpful = sum(r.helpful for r in group)
        harmful = sum(r.harmful for r in group)
        prompt = MERGE.fill(bullets=render.merge_group(group), id=first.id, helpful=helpful, harmful=harmful)
        reader = Reader(text=parse.counted_line(first.id))
        return ex.model.ask(Call(messages(prompt), params(MERGE_TEMPERATURE), reader)).output
