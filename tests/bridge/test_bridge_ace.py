"""ACE (ace_exact) против апстрима ace 82709de: шаблоны и запросы рефлектора и куратора, разборщики ответов,
операции над playbook (id, разделы, метки, статистика) и цикл online на 4 задачах эталона с той же фейковой
моделью. Генератор апстрима не сверяется: решатель общий (ACE1)."""
import json
import re
import string

import pytest

from ace import parse, prompts, render
from ace.extract.ace import bullets_used, tag_map
from ace.learner import swap
from ace.loop import run
from ace.memory import HARMFUL, HELPFUL, Lesson
from ace.methods.ace import SECTIONS, SectionedPlaybook, ace_exact, layout, question_context, section_slug
from ace.model import Reply
from ace.tasks import TASKS
from ace.verdict import yes_no
from upstream import deviation, fixture, messages

PROMPTS, PARSERS, MEMORY, LOOP = (fixture("ace", n) for n in ("prompts", "parsers", "memory", "loop"))
REFLECTOR = ["question", "reasoning_trace", "predicted_answer", "ground_truth", "environment_feedback", "bullets_used"]
CURATOR = ["current_step", "total_samples", "token_budget", "playbook_stats", "recent_reflection", "current_playbook",
           "question_context"]
GEN, REF, CUR = "You are an analysis expert", "You are an expert analyst and educator", "You are a master curator of knowledge"


def value(name):
    return f"<{name}> {{\"a\": [1]}}\nline"


def fields(template):
    return [f for _, f, _, _ in string.Formatter().parse(template) if f is not None]

# шаблоны и запросы


@pytest.mark.parametrize("ours, theirs, names", [
    ("ace_reflector", "REFLECTOR_PROMPT", REFLECTOR),
    ("ace_reflector_nogt", "REFLECTOR_PROMPT_NO_GT", [n for n in REFLECTOR if n != "ground_truth"]),
    ("ace_curator", "CURATOR_PROMPT", CURATOR),
    ("ace_curator_nogt", "CURATOR_PROMPT_NO_GT", CURATOR),
])
def test_template(ours, theirs, names):
    template = PROMPTS["templates"][theirs]
    values = {n: value(n) for n in names}
    if fields(template)[0] == "":          # у рефлектора подстановка позиционная
        want = template.format(*[values[n] for n in names])
    else:
        want = template.format(**values)
    assert prompts.load(ours).fill(values) == want


def test_empty_playbook():
    assert layout(None, SectionedPlaybook()) == PROMPTS["empty_playbook"]


def section(text, name, nxt):
    """Поле промпта апстрима между «**name:**» и «**nxt:**»."""
    return text.split(f"**{name}:**\n", 1)[1].split(f"\n\n**{nxt}:**", 1)[0]


@pytest.mark.parametrize("key", ["reflector_gt", "reflector_nogt"])
def test_reflector_request(key):
    """Записанный запрос рефлектора: наш шаблон с теми же полями, одно сообщение user, T = 0."""
    call = next(c for c in PROMPTS["filled"]["sambanova_json0"]["calls"]
                if REF in messages(c)[1] and ("Ground Truth Answer" in messages(c)[1]) == (key == "reflector_gt"))
    system, user = messages(call)
    nogt = key == "reflector_nogt"
    names = [n for n in REFLECTOR if not (nogt and n == "ground_truth")]
    nxt = {"question": "Model's Reasoning Trace", "reasoning_trace": "Model's Predicted Answer",
           "predicted_answer": "Environment Feedback" if nogt else "Ground Truth Answer",
           "ground_truth": "Environment Feedback", "environment_feedback": "Part of Playbook that's used by the generator to answer the question",
           "bullets_used": "Answer in this exact JSON format"}
    heads = {"question": "Question", "reasoning_trace": "Model's Reasoning Trace", "predicted_answer": "Model's Predicted Answer",
             "ground_truth": "Ground Truth Answer", "environment_feedback": "Environment Feedback",
             "bullets_used": "Part of Playbook that's used by the generator to answer the question"}
    values = {n: section(user, heads[n], nxt[n]) for n in names}
    assert values["environment_feedback"] == prompts.text("ace_environment_feedback", correct=nogt)
    assert prompts.load("ace_" + ("reflector_nogt" if nogt else "reflector")).fill(values) == user
    assert system == "" and call["temperature"] == 0.0 and "response_format" not in call


@pytest.mark.parametrize("key", ["curator_gt", "curator_nogt"])
def test_curator_request(key):
    calls = [c for c in PROMPTS["filled"]["sambanova_json0"]["calls"] if CUR in messages(c)[1]]
    call = calls[0 if key == "curator_gt" else 1]
    user = messages(call)[1]
    values = dict(token_budget=80000, current_step=1, total_samples=4, recent_reflection="Use plain numbers.",
                  current_playbook=section(user, "Current Playbook", "Question Context"),
                  playbook_stats=section(user, "Current Playbook Stats", "Recent Reflection"), question_context="ctx text")
    assert prompts.load("ace_curator" + ("" if key == "curator_gt" else "_nogt")).fill(values) == user


def test_json_mode_only_adds_response_format():
    """json_mode меняет только response_format; по умолчанию (run.py: --json_mode выключен) его нет, как у нас."""
    for provider in ("sambanova", "openai"):
        off, on = (PROMPTS["filled"][f"{provider}_json{m}"]["calls"] for m in (0, 1))
        assert [c["messages"] for c in off] == [c["messages"] for c in on]
        assert all(c["response_format"] == {"type": "json_object"} for c in on)

# разборщики


@pytest.mark.parametrize("row", PARSERS["extract_json_from_text"], ids=lambda r: r["in"][:30])
def test_extract_json(row):
    assert parse.ace_json(row["in"]) == row["out"]["ok"]


@pytest.mark.parametrize("row", [r for r in PARSERS["_extract_bullet_tags"] if not r["json_mode"]],
                         ids=lambda r: r["in"][:30])
def test_bullet_tags(row):
    """Без json_mode (по умолчанию в апстриме)."""
    assert parse.bullet_tags(row["in"]) == row["out"]["ok"]


@pytest.mark.parametrize("row", PARSERS["_extract_and_validate_operations"], ids=lambda r: r["in"][:30])
def test_curator_operations(row):
    got = parse.ace_operations(row["in"])
    assert got == (row["out"]["ok"]["operations"] if "ok" in row["out"] else None)


def test_bullet_ids_regex_not_ported():
    """bullet_ids генератора апстрима — регулярка по тексту: не видит ph-, верхний регистр и JSON-список. У нас id
    называет решатель строкой USED, берутся все (ACE2)."""
    deviation("ACE2")
    rows = {r["in"]: r["out"]["ok"] for r in PARSERS["_extract_bullet_ids_regex"]}
    assert rows["Used [ph-00003] and [sai-00004]."] == ["sai-00004"]
    assert rows['{"bullet_ids": ["calc-00001", "ph-00003"], "final_answer": "1"}'] == []

# память


def playbook_like_upstream():
    """Наш playbook с пунктами PLAYBOOK эталона: sai-00001 (2/0), calc-00002 (0/1), ph-00003 (0/0)."""
    m = SectionedPlaybook()
    for key, slug, text, helpful, harmful in [
            ("strategies_and_insights", "sai", "Read the units before computing.", 2, 0),
            ("formulas_and_calculations", "calc", "Operating margin = operating income / revenue * 100.", 0, 1),
            ("problem-solving_heuristics", "ph", "Check the sign of every growth rate.", 0, 0)]:
        m.ids.slug = slug
        m.add(text, key, outcomes=[HELPFUL] * helpful + [HARMFUL] * harmful)
    return m


@pytest.mark.parametrize("row", MEMORY["get_section_slug"], ids=lambda r: r["in"])
def test_section_slug(row):
    assert section_slug(row["in"]) == row["out"]["ok"]


# входы операций и меток — как в bridge/capture_ace.py (OPS, TAGS); в эталоне только выходы
OPS = {
    "add_existing_snake": [{"type": "ADD", "section": "formulas_and_calculations", "content": "A"}],
    "add_existing_header_case": [{"type": "ADD", "section": "FORMULAS & CALCULATIONS", "content": "B"}],
    "add_hyphen_header": [{"type": "ADD", "section": "PROBLEM-SOLVING HEURISTICS", "content": "C"}],
    "add_hyphen_snake": [{"type": "ADD", "section": "problem_solving_heuristics", "content": "D"}],
    "add_missing": [{"type": "ADD", "section": "no such section", "content": "E"}],
    "add_general": [{"type": "ADD", "section": "general", "content": "F"}],
    "add_no_section": [{"type": "ADD", "content": "G"}],
    "add_others": [{"type": "ADD", "section": "OTHERS", "content": "H"}],
    "update_delete_merge": [
        {"type": "UPDATE", "bullet_id": "calc-00002", "content": "changed"},
        {"type": "DELETE", "bullet_id": "sai-00001"},
        {"type": "MERGE", "source_ids": ["sai-00001", "calc-00002"], "content": "merged"},
    ],
    "unknown_type": [{"type": "FOO", "section": "OTHERS", "content": "I"}],
    "several": [
        {"type": "ADD", "section": "strategies_and_insights", "content": "J"},
        {"type": "ADD", "section": "formulas_and_calculations", "content": "K"},
        {"type": "ADD", "section": "strategies_and_insights", "content": "L"},
    ],
}
TAGS = {
    "helpful_harmful_neutral": [{"id": "sai-00001", "tag": "helpful"}, {"id": "calc-00002", "tag": "harmful"},
                                {"id": "ph-00003", "tag": "neutral"}],
    "bullet_key": [{"bullet": "calc-00002", "tag": "helpful"}],
    "unknown_id_and_tag": [{"id": "zzz-00009", "tag": "helpful"}, {"id": "sai-00001", "tag": "useful"}],
    "duplicate_id_last_wins": [{"id": "sai-00001", "tag": "helpful"}, {"id": "sai-00001", "tag": "harmful"}],
    "empty": [],
    "strings": ["sai-00001"],
}


def test_inputs_cover_fixture():
    assert {n.split("/")[0] for n in MEMORY["apply_curator_operations"]} == set(OPS)
    assert set(MEMORY["update_bullet_counts"]) == set(TAGS)


@pytest.mark.parametrize("name", sorted(OPS))
def test_apply_curator_operations(name):
    """С пустого playbook (так идёт цикл) и next_id = 4: текст playbook и следующий номер — как у апстрима."""
    text, next_id = MEMORY["apply_curator_operations"][f"{name}/empty"]["ok"]
    m = SectionedPlaybook()
    m.ids.n = 3
    m.apply(OPS[name])
    assert layout(None, m) == text and m.ids.n + 1 == next_id


def test_no_section_rejected_before_apply():
    """ADD без раздела апстрим до применения не пускает: _extract_and_validate_operations бросает, ответ пропущен."""
    assert parse.ace_operations(json.dumps(dict(reasoning="r", operations=OPS["add_no_section"]))) is None


def test_general_goes_on_top_of_others():
    """Пункты раздела general встают сразу под заголовок OTHERS, выше прежних (apply_curator_operations)."""
    m = SectionedPlaybook()
    m.apply([dict(type="ADD", section="OTHERS", content="a")])
    m.apply([dict(type="ADD", section="general", content="b"), dict(type="ADD", section="general", content="c"),
             dict(type="ADD", section="OTHERS", content="d")])
    assert layout(None, m).endswith("## OTHERS\n[gene-00002] helpful=0 harmful=0 :: b\n[gene-00003] helpful=0 harmful=0 :: c\n"
                                     "[misc-00001] helpful=0 harmful=0 :: a\n[misc-00004] helpful=0 harmful=0 :: d")


def test_bad_section_skips_whole_reply():
    """Раздел не строкой: апстрим падает внутри apply_curator_operations и оставляет playbook как был."""
    m = SectionedPlaybook()
    m.apply([dict(type="ADD", section="OTHERS", content="a"), dict(type="ADD", section=None, content="b")])
    assert m.records() == [] and m.ids.n == 0


def counts(text):
    return {i: (int(h), int(b)) for i, h, b in re.findall(r"\[([^\]]+)\] helpful=(\d+) harmful=(\d+)", text)}


@pytest.mark.parametrize("name", list(MEMORY["update_bullet_counts"]))
def test_update_bullet_counts(name):
    m = playbook_like_upstream()
    tags = tag_map(TAGS[name])
    m.count([i for i, t in tags.items() if t == "helpful"], [i for i, t in tags.items() if t == "harmful"])
    assert {r.id: (r.helpful, r.harmful) for r in m.records()} == counts(MEMORY["update_bullet_counts"][name]["ok"])


def test_playbook_stats():
    assert playbook_like_upstream().stats() == MEMORY["get_playbook_stats"]["ok"]


@pytest.mark.parametrize("row", MEMORY["extract_playbook_bullets"], ids=lambda r: ",".join(r["ids"]) or "none")
def test_extract_playbook_bullets(row):
    assert bullets_used(playbook_like_upstream(), row["ids"]) == row["out"]["ok"]


def test_format_playbook_line():
    m = SectionedPlaybook()
    m.ids.slug = "calc"
    assert render.counted(m.add("text", "formulas_and_calculations")) == MEMORY["format_playbook_line"]["ok"]


def test_question_context():
    """DataProcessor апстрима: у formula контекст пуст, у finer — текст после «Input: »."""
    ok = fixture("ace", "eval")
    assert question_context("formula", "x Question: \"q\". Answer:") == ok["parse_context_and_question_formula"]["ok"][0]
    text = "Instruction: Tag the numbers.\nInput: Revenue was $5 million.\nAnswer: "
    assert question_context("finer", text) == ok["parse_instruction_and_input"]["ok"][0]

# цикл online на 4 задачах: фейк апстрима (bridge/capture_ace.py) — ответы решателя по задаче и по тому, была ли
# рефлексия; рефлектор и куратор — записанные ответы по порядку


ANSWERS = {"Alpha": ("15.00", "15.00"), "Beta": ("$40.00", "40.00"), "Gamma": ("3.0", "3.0"), "Delta": ("1,200.00", "1,200.00")}
UPSTREAM_ID = re.compile(r"\[([a-z]{3,}-\d{5})\]")      # _extract_bullet_ids_regex апстрима (generator.py:115)


class Task:
    name, system, instr = "formula", "SYSTEM", "INSTR"

    def __init__(self, samples):
        self.samples = samples

    def load(self, split="", size=None):
        return [dict(context=s["question"], target=s["target"]) for s in self.samples]

    def check(self, answer, target):
        return TASKS["formula"].check(answer, target)

    def accuracy(self, answers, targets):
        return TASKS["formula"].accuracy(answers, targets)


def generator_json(system, user):
    """Ответ генератора фейка апстрима (capture_ace.generator_reply) на наш промпт: id — из показанного playbook."""
    task = next(t for t in ANSWERS if t in user)
    reflected = "\n\nReflection:\n" in user
    ids = re.findall(r"\[([^\]\s]+)\] helpful=", system)
    return json.dumps({"reasoning": f"Task {task}. Used bullets {' '.join(f'[{i}]' for i in ids)}. Reflected: {reflected}.",
                       "bullet_ids": ids, "final_answer": ANSWERS[task][reflected]})


class Replay:
    name, max_tokens = "replay", 4096

    def __init__(self, upstream):
        self.replies = {m: iter([c["response"] for c in upstream if messages(c)[1].startswith(m)]) for m in (REF, CUR)}
        self.calls = []

    def run(self, system, user, output=str, tools=(), deps=None, rounds=0, temperature=0, max_tokens=None, on_step=None,
            top_p=None):
        self.calls.append(dict(system=system, user=user, temperature=temperature))
        role = next((m for m in (REF, CUR) if user.startswith(m)), None)
        if role:
            text = next(self.replies[role])
        else:
            # решатель называет те id, что апстрим вынул бы регуляркой из своего ответа (ACE2), и ответ — строкой
            # FINAL ANSWER (ACE1)
            gen = generator_json(system, user)
            text = f"{gen}\nUSED: {', '.join(UPSTREAM_ID.findall(gen))}\nFINAL ANSWER: {json.loads(gen)['final_answer']}"
        return Reply(text, text, False, [])

    def one(self, system, user, temperature=0, max_tokens=None):
        return self.run(system, user, temperature=temperature)

    def usage(self):
        return dict(calls=len(self.calls), prompt_tokens=0, completion_tokens=0)


def solver_tail(text):
    """Строки USED и FINAL ANSWER нашего решателя — в траектории, которую видит рефлектор (ACE1)."""
    return re.sub(r"\nUSED: [^\n]*\nFINAL ANSWER: [^\n]*", "", text)


@pytest.mark.parametrize("key", ["online_gt", "online_nogt"])
def test_online_loop(tmp_path, key):
    """Запросы рефлектора и куратора — посимвольно и по порядку, раунды рефлексии, итоговый playbook и номер.
    Генерации апстрима вне обучения (начальный тест, тест окна, решение после куратора) не делаем (ACE3)."""
    deviation("ACE1", "ACE2", "ACE3")
    up = LOOP[key]
    assert up["config"]["json_mode"] is False and up["config"]["max_num_rounds"] == 3
    model = Replay(up["calls"])
    learner = ace_exact if key == "online_gt" else swap(ace_exact, verdict=yes_no)
    run(Task(up["samples"]), learner, model, len(up["samples"]), str(tmp_path))
    theirs = [messages(c)[1] for c in up["calls"] if not messages(c)[1].startswith(GEN)]
    ours = [solver_tail(c["user"]) for c in model.calls if c["user"].startswith((REF, CUR))]
    assert ours == theirs
    assert all(c["system"] == "" and c["temperature"] == 0 for c in model.calls if c["user"].startswith((REF, CUR)))
    memory = json.load(open(tmp_path / "memory.json"))
    final = SectionedPlaybook()
    for r in memory:
        final.sections[r["section"]].items.append(Lesson(r["id"], r["text"], r["outcomes"]))
    assert layout(None, final) == up["final_playbook"]
    assert max(int(r["id"].rsplit("-", 1)[1]) for r in memory) + 1 == up["next_global_id"]


def test_online_rounds():
    """Раунды: неверный ответ — до 3 пар «рефлексия -> новая попытка», верный — одна рефлексия."""
    up = LOOP["online_gt"]
    theirs = [c["response"] for c in up["calls"] if messages(c)[1].startswith(REF)]
    assert [json.loads(r)["reasoning"] for r in theirs] == [
        "Reflection on Alpha.", "Reflection on Beta.", "Reflection on Gamma.", "Reflection on Gamma.",
        "Reflection on Gamma.", "Reflection on Delta."]


def test_sections_are_upstream():
    assert "\n\n".join(f"## {s}" for s in SECTIONS) == PROMPTS["empty_playbook"]
