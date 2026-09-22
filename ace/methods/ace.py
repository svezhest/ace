"""ACE (Agentic Context Engineering). Два варианта.

ace — вариант стенда, основа цепочки абляций:
    1 память      пункты со счётчиками helpful / harmful
    2 инжект      вся память
    3 сигнал      верный ответ
    4 обновление  reflector: уроки и метки пунктов -> curator правит память -> удаление вредных пунктов

ace_exact — как в апстриме (ace/ace/ace.py, core/, playbook_utils.py; промпты prompts/ace_*.txt дословно):
    1 память      playbook из 7 разделов, пункты только добавляются
    2 инжект      весь playbook, строка пункта «[id] helpful=X harmful=Y :: текст»
    3 сигнал      верный ответ и id пунктов, которые решатель назвал сам (строка USED вместо bullet_ids)
    4 обновление  при неверном ответе до 3 раундов: reflector метит названные пункты, счётчики растут,
                  решатель пробует снова с рефлексией; при верном один раунд; куратор видит последнюю
                  рефлексию, контекст вопроса, бюджет токенов и статистику playbook, отвечает только ADD
    Решение после куратора в апстриме только для отчёта, память не меняет: не делаем.
    Слияние похожих пунктов (BulletpointAnalyzer) в апстриме выключено: вариант ace_exact_dedup.
"""
import json
from typing import Literal

from pydantic import BaseModel

from pathlib import Path

from .. import embed, fs, inject, update
from ..feedback import Episode, Feedback
from ..inject import View
from ..loop import Method, swap
from ..memory import ALL
from ..update import Delta, Update, snapshot

# 1. память

MEMORY = {"bullet": ALL}

# 4. обновление

REFLECT = """Compare the attempted solution with the correct answer and extract at most 3 short lessons
that would help solve similar tasks. Also name the memory bullets that helped and the ones that misled.
{form}

## Task
{question}

## Attempted solution
{output}

## Verdict
{verdict}

## Memory bullets available during the attempt
{memory}"""

CURATE = """Merge the lessons into memory using the tools: create a bullet in memory/ only if it is genuinely new and transferable,
edit a bullet (read it first) if a lesson refines it. Do nothing for duplicates. When done, reply "done".

## Lessons
{lessons}

## Memory
{memory}"""


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


def reflect(format="json"):
    """format: json — маленькая схема; text — свободное письмо, куратор разбирает его сам."""
    def reflect(ctx, ep, memory):
        prompt = REFLECT.format(question=ep.question, output=ep.output, verdict=ep.verdict(),
                                memory=memory.text() or "(empty)", form="Write freely." if format == "text" else "")
        if format == "text":
            text = ctx.model.one("You are a reflector.", prompt).output
            return Delta(lessons=[text]) if text else None
        r = ctx.model.run("You are a reflector.", prompt, output=Reflection).output
        return Delta(lessons=r.lessons, helpful=r.helpful, harmful=r.harmful) if r else None
    return reflect


def curate(mode="tools"):
    """mode: tools — файловые инструменты по одной операции; json — все операции одной схемой; rewrite — вся память заново."""
    def curate(ctx, memory, deltas):
        for d in deltas:
            update.count(memory, d.helpful, d.harmful)
            if d.lessons:
                merge(ctx.model, memory, d.shown(), mode)
    return curate


def merge(model, memory, lessons, mode):
    if mode == "tools":
        files = "\n".join(f"memory/{r.id}: {r.text}" for r in memory.records) or "(empty)"
        model.run("You are a curator.", CURATE.format(lessons=lessons, memory=files),
                  tools=fs.TOOLS, deps=fs.FS({"memory": fs.Mount(memory)}), rounds=6)
        return
    prompt = CURATE.format(lessons=lessons, memory=memory.text() or "(empty)")
    if mode == "json":
        r = model.run("You are a curator.", prompt.replace("using the tools", "as a list of ADD/UPDATE operations"), output=Ops).output
        for op in (r.ops if r else []):
            if op.op == "ADD":
                memory.add(op.text)
            elif memory.get(op.id):
                memory.edit(op.id, op.text)
    else:
        new = model.one("You are a curator.", prompt.replace("using the tools", "by rewriting the whole memory")
                        .replace('reply "done"', "return only the new memory, one bullet per line")).output
        if new:
            memory.rewrite(next(iter(memory.schema)), new.strip())


def prune(ctx, memory, before):
    for r in list(memory.records):
        if r.harmful >= 3 and r.harmful > r.helpful:
            memory.drop(r.id)


ace = Method("ace", MEMORY, inject.full(), Feedback("golden"),
             Update(reflect(), curate(), prune))

# ace_exact

PROMPTS = Path(__file__).parent / "prompts"
P = {n: (PROMPTS / f"ace_{n}.txt").read_text() for n in ("reflector", "reflector_nogt", "curator", "curator_nogt")}
SECTIONS = ["STRATEGIES & INSIGHTS", "FORMULAS & CALCULATIONS", "CODE SNIPPETS & TEMPLATES", "COMMON MISTAKES TO AVOID",
            "PROBLEM-SOLVING HEURISTICS", "CONTEXT CLUES & INDICATORS", "OTHERS"]
ROUNDS, TOKEN_BUDGET = 3, 80000

PLAYBOOK = {"bullet": ("add",)}


def slug(section):
    return section.lower().strip().replace(" ", "_").replace("&", "and")


def line(r):
    return f"[{r.id}] helpful={r.helpful} harmful={r.harmful} :: {r.text}"


def playbook_text(memory):
    return "\n\n".join("\n".join([f"## {s}"] + [line(r) for r in memory.records if r.meta["section"] == slug(s)])
                        for s in SECTIONS)


def playbook(model, memory, item):
    return View(playbook_text(memory), [r.id for r in memory.records]) if memory.records else View()


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


def tags(memory, diagnosis):
    """update_bullet_counts: helpful и harmful по меткам reflector, neutral не считается."""
    helpful = [t.id for t in diagnosis.bullet_tags if t.tag == "helpful"]
    harmful = [t.id for t in diagnosis.bullet_tags if t.tag == "harmful"]
    update.count(memory, helpful, harmful)
    return helpful, harmful


def diagnose(ctx, question, attempt, memory, feedback, target):
    used = [line(memory.get(i)) for i in attempt.used if memory.get(i)]
    bullets = "\n".join(used) if attempt.used else "(No bullets used by generator)"
    if target:
        prompt = P["reflector"].format(question, attempt.output, attempt.answer, target, feedback, bullets)
    else:
        prompt = P["reflector_nogt"].format(question, attempt.output, attempt.answer, feedback, bullets)
    return ctx.model.run("", prompt, output=Diagnosis).output


def exact_reflect(ctx, ep, memory):
    """Раунды рефлексии на копии памяти: счётчики копии растут, решатель видит их при новой попытке."""
    local, helpful, harmful = snapshot(memory), [], []
    attempt, reflection = ep, None
    for _ in range(ROUNDS if ep.ok is False else 1):
        feedback = "Predicted answer matches ground truth" if attempt.ok else "Predicted answer does not match ground truth"
        d = diagnose(ctx, ep.question, attempt, local, feedback, ep.target)
        if not d:
            break
        reflection = d.model_dump_json(indent=2)
        h, x = tags(local, d)
        helpful, harmful = helpful + h, harmful + x
        if attempt.ok:
            break
        retry = ctx.retry(local, reflection)
        attempt = Episode(ep.question, retry.output, retry.answer, retry.steps, retry.truncated,
                          used=retry.reported, ok=ctx.task.check(retry.answer, ep.target))
        if attempt.ok:
            break
    if not reflection:
        return None
    return Delta(lessons=[reflection], helpful=helpful, harmful=harmful, episode=dict(text=ep.question, labeled=bool(ep.target)))


def exact_curate(ctx, memory, deltas):
    for d in deltas:
        update.count(memory, d.helpful, d.harmful)
        stats = playbook_stats(memory)
        prompt = P["curator" if d.episode["labeled"] else "curator_nogt"].format(
            token_budget=TOKEN_BUDGET, current_step=ctx.step, total_samples=ctx.total,
            playbook_stats=json.dumps(stats, indent=2), recent_reflection=d.lessons[-1],
            current_playbook=playbook_text(memory), question_context=d.episode["text"])
        r = ctx.model.run("", prompt, output=Curation).output
        for op in (r.operations if r else []):
            if op.type == "ADD":
                section = slug(op.section)
                memory.add(op.content, meta=dict(section=section if section in map(slug, SECTIONS) else "others"))


def playbook_stats(memory):
    stats = dict(total_bullets=0, high_performing=0, problematic=0, unused=0, by_section={})
    for s in SECTIONS:
        for r in (r for r in memory.records if r.meta["section"] == slug(s)):
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


MERGE = """You are merging similar playbook bulletpoints into a single, comprehensive entry.

Given these similar bulletpoints:
{bullets}

Merge them into ONE bulletpoint that captures all important information while removing redundancy.

Requirements:
1. Keep the ID from the first entry: [{id}]
2. Use combined counts: helpful={helpful} harmful={harmful}
3. Combine the content to be comprehensive but concise
4. Output ONLY in this format: [{id}] helpful={helpful} harmful={harmful} :: [merged content]

Do NOT include any explanation, just output the merged bulletpoint."""


def analyzer(threshold=0.85):
    """BulletpointAnalyzer: группы по всем парам с косинусом >= threshold, группу сливает LLM (T=0.3),
    остаётся первый пункт. Порог апстрима 0.90 подобран под all-mpnet; у BGE-M3 косинусы ниже, отсюда 0.85."""
    def bound(ctx, memory, before):
        recs = list(memory.records)
        if len(recs) < 2:
            return
        sims, seen = embed.embed([r.text for r in recs]) @ embed.embed([r.text for r in recs]).T, set()
        for i in range(len(recs)):
            if i in seen:
                continue
            group = [i] + [j for j in range(i + 1, len(recs)) if sims[i][j] >= threshold]
            if len(group) == 1:
                continue
            seen.update(group)
            first, rest = recs[i], [recs[j] for j in group[1:]]
            helpful, harmful = sum(recs[j].helpful for j in group), sum(recs[j].harmful for j in group)
            out = (ctx.model.one("", MERGE.format(bullets="\n".join(f"{k + 1}. {line(recs[j])}" for k, j in enumerate(group)),
                                                  id=first.id, helpful=helpful, harmful=harmful), temperature=0.3).output or "").strip()
            if out.startswith(f"[{first.id}]") and "::" in out:
                counts, text = out.split("]", 1)[1].split("::", 1)
                counts = dict(kv.split("=", 1) for kv in counts.split() if "=" in kv)
                if counts.get("helpful", "").isdigit() and counts.get("harmful", "").isdigit():
                    memory.edit(first.id, text.strip())
                    first.helpful, first.harmful = int(counts["helpful"]), int(counts["harmful"])
            for r in rest:
                memory.drop(r.id)
    return bound


ace_exact = Method("ace_exact", PLAYBOOK, playbook, Feedback("golden", usage="self"),
                   Update(exact_reflect, exact_curate, needs_usage=True))
ace_exact_dedup = swap(ace_exact, "ace_exact_dedup", memory={"bullet": ("add", "edit", "delete")}, bound=analyzer())
