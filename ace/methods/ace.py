"""ACE (Agentic Context Engineering). Два варианта из одних блоков.

ace — вариант стенда, основа цепочки абляций:
    1 память      пункты со всеми операциями и счётчиками helpful / harmful
    2 инжект      все пункты «[id] текст»
    3 сигнал      верный ответ
    4 обновление  reflect: ask -> уроки и метки пунктов; curate: счётчики, затем пункты правит агент файловыми
                  инструментами (или одной схемой операций, или перезаписью); bound: prune вредных

ace_exact — как в апстриме (ace/ace/ace.py, core/, playbook_utils.py; промпты prompts/ace_*.txt дословно):
    1 память      playbook: пункты по 7 разделам (поле group), только добавляются
    2 инжект      весь playbook по разделам, строка «[id] helpful=X harmful=Y :: текст»
    3 сигнал      верный ответ и id пунктов, названных решателем (строка USED вместо bullet_ids)
    4 обновление  reflect: rounds(ask) — при неверном ответе до 3 раундов «рефлексия -> счётчики -> новая
                  попытка»; curate: счётчики, затем куратор (последняя рефлексия, вопрос, бюджет токенов,
                  статистика playbook) отвечает ADD с разделом
    Решение после куратора в апстриме только для отчёта: не делаем.
    ace_exact_dedup: bound merge_similar — BulletpointAnalyzer (в апстриме выключен).
"""
import json
from typing import Literal

from pydantic import BaseModel

from .. import bound, curate, fs, inject, prompts, reflect
from ..feedback import Feedback
from ..inject import counted
from ..loop import Method, swap
from ..memory import ALL
from ..update import Delta, Update, ask

# ace

MEMORY = {"bullet": ALL}

REFLECT = prompts.load("ace_stand_reflect.txt")
CURATE = prompts.load("ace_stand_curate.txt")
CURATE_JSON = prompts.Prompt(CURATE.text.replace("using the tools", "as a list of ADD/UPDATE operations"))
CURATE_REWRITE = prompts.Prompt(CURATE.text.replace("using the tools", "by rewriting the whole memory")
                                .replace('reply "done"', "return only the new memory, one bullet per line"))


class Reflection(BaseModel):
    lessons: list[str]
    helpful: list[str] = []
    harmful: list[str] = []


class Op(BaseModel):
    op: Literal["ADD", "UPDATE"]
    text: str
    id: str = ""


class Ops(BaseModel):
    ops: list[Op]


def reflect_fields(form):
    return lambda ctx, ep, memory, **extra: dict(question=ep.question, output=ep.output, verdict=ep.verdict(),
                                                 memory=memory.text() or "(empty)", form=form)


def stand_reflect(format="json"):
    """format: json — маленькая схема; text — свободное письмо, куратор разбирает его сам."""
    if format == "text":
        return ask(REFLECT, reflect_fields("Write freely."), system="You are a reflector.",
                   then=lambda text, *_, **__: Delta(lessons=[text]) if text else None)
    return ask(REFLECT, reflect_fields(""), Reflection, system="You are a reflector.",
               then=lambda r, *_, **__: Delta(lessons=r.lessons, helpful=r.helpful, harmful=r.harmful) if r else None)


def lessons_and(memory_text):
    return lambda ctx, memory, d: dict(lessons=d.shown(), memory=memory_text(memory))


def stand_curate(mode="tools"):
    """mode: tools — файловые инструменты по одной операции; json — все операции одной схемой; rewrite — вся память заново."""
    if mode == "tools":
        files = lambda memory: "\n".join(f"memory/{r.id}: {r.text}" for r in memory.records) or "(empty)"
        merge = curate.tools(CURATE, lessons_and(files), lambda memory, d: fs.FS({"memory": fs.Mount(memory)}), rounds=6)
    elif mode == "json":
        merge = ask(CURATE_JSON, lessons_and(lambda m: m.text() or "(empty)"), Ops, system="You are a curator.",
                    then=curate.apply_ops(lambda r: [dict(operation=o.op, id=o.id, content=o.text) for o in (r.ops if r else [])],
                                          missing="skip"))
    else:
        merge = ask(CURATE_REWRITE, lessons_and(lambda m: m.text() or "(empty)"), system="You are a curator.",
                    then=lambda new, ctx, memory, d, **_: new and memory.rewrite(next(iter(memory.schema)), new.strip()))
    return curate.each(curate.count, curate.admit(lambda ctx, memory, d: bool(d.lessons), merge))


harmful = bound.prune(lambda r: r.harmful >= 3 and r.harmful > r.helpful)

ace = Method("ace", MEMORY, inject.full(), Feedback("golden"), Update(stand_reflect(), stand_curate(), harmful))

# ace_exact

P = {n: prompts.load(f"ace_{n}.txt", "positional" if n.startswith("reflector") else "format")
     for n in ("reflector", "reflector_nogt", "curator", "curator_nogt")}
SECTIONS = ["STRATEGIES & INSIGHTS", "FORMULAS & CALCULATIONS", "CODE SNIPPETS & TEMPLATES", "COMMON MISTAKES TO AVOID",
            "PROBLEM-SOLVING HEURISTICS", "CONTEXT CLUES & INDICATORS", "OTHERS"]
ROUNDS, TOKEN_BUDGET = 3, 80000

PLAYBOOK = {"bullet": ("add",)}


def slug(section):
    return section.lower().strip().replace(" ", "_").replace("&", "and")


LAYOUT = inject.by_group(counted, order=[(slug(s), s) for s in SECTIONS])
playbook = inject.show(layout=LAYOUT)


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


class Addition(BaseModel):
    type: str = "ADD"
    section: str = "others"
    content: str


class Curation(BaseModel):
    reasoning: str
    operations: list[Addition] = []


def diagnosis_fields(ctx, ep, memory, **extra):
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


exact_reflect = reflect.rounds(ask(lambda ep, memory, **_: P["reflector"] if ep.target else P["reflector_nogt"],
                                   diagnosis_fields, Diagnosis, then=diagnosis_delta), ROUNDS)


def playbook_stats(memory):
    stats = dict(total_bullets=0, high_performing=0, problematic=0, unused=0, by_section={})
    for s in SECTIONS:
        for r in (r for r in memory.records if r.group == slug(s)):
            stats["total_bullets"] += 1
            if r.helpful > 5 and r.harmful < 2:
                stats["high_performing"] += 1
            elif r.harmful >= r.helpful and r.harmful > 0:
                stats["problematic"] += 1
            elif r.helpful + r.harmful == 0:
                stats["unused"] += 1
            sec = stats["by_section"].setdefault(s, dict(count=0, helpful=0, harmful=0))
            sec["count"] += 1
            sec["helpful"] += r.helpful
            sec["harmful"] += r.harmful
    return stats


def curator_fields(ctx, memory, d, **extra):
    return dict(token_budget=TOKEN_BUDGET, current_step=ctx.step, total_samples=ctx.total,
                playbook_stats=json.dumps(playbook_stats(memory), indent=2), recent_reflection=d.lessons[-1],
                current_playbook=LAYOUT(memory.records), question_context=d.info["question"])


def section(name):
    return slug(name) if slug(name) in map(slug, SECTIONS) else "others"


exact_curate = curate.each(curate.count, ask(lambda memory, d, **_: P["curator" if d.info["labeled"] else "curator_nogt"],
                                             curator_fields, Curation,
                                             then=curate.add(lambda r: [op for op in (r.operations if r else []) if op.type == "ADD"],
                                                             text=lambda op: op.content, group=lambda op: section(op.section))))

MERGE = prompts.load("ace_merge.txt")


def llm_merge(ctx, group):
    """Слияние группы похожих пунктов по промпту BulletpointAnalyzer; ответ «[id] helpful=N harmful=M :: текст»."""
    first = group[0]
    helpful, harmful = sum(r.helpful for r in group), sum(r.harmful for r in group)
    out = (ctx.model.one("", MERGE.fill(dict(bullets="\n".join(f"{k + 1}. {counted(r)}" for k, r in enumerate(group)),
                                             id=first.id, helpful=helpful, harmful=harmful)), temperature=0.3).output or "").strip()
    if not (out.startswith(f"[{first.id}]") and "::" in out):
        return None
    counts, text = out.split("]", 1)[1].split("::", 1)
    counts = dict(kv.split("=", 1) for kv in counts.split() if "=" in kv)
    if not (counts.get("helpful", "").isdigit() and counts.get("harmful", "").isdigit()):
        return None
    return text.strip(), int(counts["helpful"]), int(counts["harmful"])


ace_exact = Method("ace_exact", PLAYBOOK, playbook, Feedback("golden", usage="self"),
                   Update(exact_reflect, exact_curate, needs_usage=True))
# порог апстрима 0.90 подобран под all-mpnet; у BGE-M3 косинусы ниже
ace_exact_dedup = swap(ace_exact, "ace_exact_dedup", memory={"bullet": ("add", "edit", "delete")},
                       bound=bound.merge_similar(0.85, llm_merge))
