"""Мостик к TF-GRPO (youtu-agent c2caa53, utu/practice/experience_updater.py): промпты, разбор ответов, план батча,
фильтр групп, два батча цикла обновления и температуры против эталонов bridge/fixtures/tfgrpo. Фейковая модель
отвечает так же, как фейк апстрима: по тексту промпта из записанных запросов."""
import importlib
import json

import jinja2
import pytest
import yaml
from upstream import deviation, fixture, messages

from ace import render, verdict
from ace.extract import OPERATIONS, Extraction
from ace.extract import tfgrpo as T
from ace.loop import Episode, Group, Prompt
from ace.memory import Lesson
from ace.model import roles, text_reply
from ace.tasks import TASKS

U = importlib.import_module("ace.upstream.tfgrpo")      # пары промптов обучения апстрима
M = importlib.import_module("ace.methods.tfgrpo")      # имя tfgrpo в пакете занято самим методом
MEM = importlib.import_module("ace.memory.tfgrpo")
SHOW = importlib.import_module("ace.solver.tfgrpo")

PROMPTS, PARSERS, MEMORY = fixture("tfgrpo", "prompts"), fixture("tfgrpo", "parsers"), fixture("tfgrpo", "memory")
LOOP, CONFIG = fixture("tfgrpo", "loop"), fixture("tfgrpo", "config")
# цели, с которыми снят эталон (bridge/capture_tfgrpo.py: AGENT_OBJ, LEARN_OBJ)
AGENT_OBJ = "input: A math question\noutput: A step-by-step reasoning process that leads to the final answer\n"
LEARN_OBJ = "Help the agent to improve the solving capability on math questions by extracting general and concise guidelines.\n"
STAGES = ["single_rollout_summary_template", "single_query_group_advantage", "group_experience_update_template",
          "batch_experience_update_template"]
MARKERS = ["<Working Agent Input>", "<Agent Input>", "<Existing Experiences>", "<Experiences and Proposed Operations>"]


class Fake:
    """Отвечает по (системный, пользовательский) промпт из записанных запросов апстрима или заданной функцией."""
    def __init__(self, calls=(), answer=None):
        self.replies = {messages(c): c["response"] for c in calls}
        self.answer, self.calls = answer, []

    def ask(self, call):
        system, user = roles(call.messages)
        self.calls.append(dict(system=system, user=user, params=call.params))
        if self.answer:
            return text_reply(call, self.answer(user))
        assert (system, user) in self.replies, f"запроса нет в эталоне:\n{user[:300]}"
        return text_reply(call, self.replies[system, user])


class Task:
    name = "bridge"


class Ex:
    task, training = Task(), True

    def __init__(self, model):
        self.model = model


@pytest.fixture(autouse=True)
def upstream_objectives(monkeypatch):
    """Цели задачи стенда -> цели, с которыми снят эталон."""
    deviation("S2")
    monkeypatch.setitem(U.OBJECTIVE, Task.name, AGENT_OBJ)
    monkeypatch.setattr(U, "LEARNING", LEARN_OBJ)


def stage(user):
    return next(i for i, m in enumerate(MARKERS) if user.startswith(m))


def trajectory(case, i, reward):
    """Траектория, как её печатает промпт сводки апстрима: repr списка сообщений агента."""
    return str([{"role": "user", "content": f"Problem {case}"},
                {"role": "assistant", "content": f"attempt {i} of {case}: answer {'42' if reward else '41'}"}])


def group(case, rewards, target="42", output=trajectory):
    """Группа rollout с наградами rewards (в зачёт у TF-GRPO — итоговый агент, не попытка группы)."""
    eps = [Episode(f"Problem {case}", k, Prompt(), output(case, k, r), "", "", [], False, [], [], [], ok=bool(r),
                   target=target) for k, r in enumerate(rewards)]
    return Group(f"Problem {case}", eps, target=target)


def library(texts):
    m = MEM.Library()
    for t in texts:
        m.add(t)
    return m

# промпты


@pytest.mark.parametrize("key", PROMPTS["templates"])
def test_templates(key):
    """Шаблон апстрима (jinja2.Template, как FileUtils.get_jinja_template_str) и наш дают одно и то же."""
    name, part = key.lower().rsplit("_", 1)
    values = dict(agent_objective=AGENT_OBJ, learning_objective=LEARN_OBJ, num_experiences=2, question="Q", trajectory="T",
                  answer="A", critique="C", trajectories="TS", existing_experiences="E", new_experiences="N",
                  experiences_and_operations="EO")
    ours = U.P[name][part == "up"]
    assert ours.fill(**values) == jinja2.Template(PROMPTS["templates"][key]).render(**values)


def test_objectives_form():
    """Цели апстрима — yaml-блоки с переводом строки в конце; наши той же формы."""
    practice = CONFIG["math_reasoning"]["practice"]
    for text in [practice["agent_objective"], practice["learning_objective"], *U.OBJECTIVE.values(), U.LEARNING]:
        assert text.endswith("\n") and not text.endswith("\n\n")
    assert all(t.startswith("input: ") and "\noutput: " in t for t in list(U.OBJECTIVE.values()) + [practice["agent_objective"]])


def test_summary_requests():
    """Сводка каждой попытки: вопрос, ответ или [REDACTED], критика по умолчанию (у math апстрима reasoning = None)."""
    for case, labeled in (("summary_gt", True), ("summary_no_gt", False)):
        calls = PROMPTS["requests"][case]
        model = Fake(calls)
        g = group("A", [1, 0][:len(calls)], target="42" if labeled else "")
        # критика эталона: у первой попытки "Correct.", у второй нет; у math апстрима её нет никогда (test_loop)
        for e, critique, call in zip(T.rollouts(g, False), ["Correct.", render.TFGRPO.no_critique()], calls):
            U.ask(Ex(model), STAGES[0], question=e.question, trajectory=e.output, answer=g.target or render.TFGRPO.redacted(),
                  critique=critique)
            assert model.calls[-1]["user"] == messages(call)[1]
        assert model.calls[0]["system"] == messages(calls[0])[0]


def test_advantage_requests():
    for case, labeled in (("advantage_gt", True), ("advantage_no_gt", False)):
        call = PROMPTS["requests"][case][0]
        g = group("A", [1, 0], target="42" if labeled else "")
        user = U.P[STAGES[1]][1].fill(question=g.question, answer=g.target or render.TFGRPO.redacted(),
                                      trajectories=render.attempts(list(zip(T.rollouts(g, False), ["S0", "S1"])), labeled))
        assert user == messages(call)[1]


def test_group_update_requests():
    for case, texts in (("group_update_empty_library", []),
                        ("group_update_library", ["Units: check units.", "Verify: recompute."])):
        call = PROMPTS["requests"][case][0]
        model = Fake([call])
        ops = T.operations(U.ask(Ex(model), STAGES[2], existing_experiences=render.experiences(library(texts).records()),
                                 new_experiences="1. Rule A: check the arithmetic of A."))
        assert model.calls[0]["user"] == messages(call)[1]
        assert ops == [{"operation": "ADD", "id": None, "content": "Rule A: check the arithmetic of A."}]


def test_batch_requests():
    """План батча: таблица опытов с операциями; без операций — «No batch operations.»; ответ применяется."""
    call = PROMPTS["requests"]["batch_update"][0]
    m = library(["Units: check units.", "Verify: recompute."])
    ops = [{"operation": "UPDATE", "id": "G0", "content": "Units: check units twice."},
           {"operation": "ADD", "id": None, "content": "Rule A: check the arithmetic of A."}]
    model = Fake([call])
    m.learn(Ex(model), [Extraction(None, [], [], {OPERATIONS: ops})])
    assert (model.calls[0]["system"], model.calls[0]["user"]) == messages(call)
    assert [r.text for r in m.records()] == ["Units: check units twice.", "Verify: recompute.", "Rule A: check the arithmetic of A."]
    call = PROMPTS["requests"]["batch_update_no_ops"][0]
    model = Fake([call])
    library([]).learn(Ex(model), [Extraction(None, [], [], {OPERATIONS: []})])
    assert model.calls[0]["user"] == messages(call)[1]

# разбор ответов


@pytest.mark.parametrize("name", PARSERS["advantage"])
def test_parse_advantage(name):
    """<Experiences> без учёта регистра, первый блок; без пары — пустая строка (группа всё равно идёт в сверку)."""
    case = PARSERS["advantage"][name]
    assert [T.EXPERIENCES.read(case["response"])] == case["experiences"]


@pytest.mark.parametrize("name", PARSERS["group_update"])
def test_parse_group_update(name):
    """Последний ```json или весь текст; ```JSON и ``` без json — группа выпадает (у нас: без операций)."""
    case = PARSERS["group_update"][name]
    ops = T.operations(case["response"])
    if case["dropped"]:
        assert ops == []
    elif not isinstance(case["operations"][0], list):
        deviation("TF4")        # объект вместо списка: у апстрима доходит до плана и роняет его
        assert ops == []
    else:
        assert ops == case["operations"][0]


@pytest.mark.parametrize("name", PARSERS["batch_update"])
def test_parse_batch_update(name):
    """План батча: до трёх попыток разобрать JSON; разобрался — план применяется."""
    case = PARSERS["batch_update"][name]
    m = library(["old"])
    model = Fake(answer=lambda user: case["response"])
    m.learn(Ex(model), [Extraction(None, [], [], {OPERATIONS: [{"operation": "ADD", "content": "X"}]})])
    assert len(model.calls) == case["llm_calls"]
    if "error" in case["experiences"]:
        deviation("TF4")        # план-объект: у апстрима падение, у нас план пуст
        assert [r.text for r in m.records()] == ["old"]
    else:
        assert [r.text for r in m.records()] == list(case["experiences"].values())

# память


@pytest.mark.parametrize("name", MEMORY["batch_update"])
def test_batch_update(name):
    """Применение плана: ADD в конец, UPDATE на месте (неизвестная метка — добавляет), DELETE, пустой content и
    неизвестные операции пропускаются; порядок опытов — порядок ключей апстрима, после плана метки G0, G1, ..."""
    case = MEMORY["batch_update"][name]
    m = library(case["before"].values())
    model = Fake(answer=lambda user: "```json\n" + json.dumps(case["plan"]) + "\n```")
    m.learn(Ex(model), [Extraction(None, [], [], {OPERATIONS: [{"operation": "ADD", "content": "X"}]})])
    assert [r.text for r in m.records()] == list(case["after"].values())


@pytest.mark.parametrize("name", MEMORY["format_exp_and_ops"])
def test_batch_table(name):
    """_format_exp_and_ops = render.batch_table: опыты по меткам и их операции, затем операции без id."""
    case = MEMORY["format_exp_and_ops"][name]
    assert list(case["experiences"]) == [render.label(i) for i in range(len(case["experiences"]))]
    records = [Lesson(f"r{i}", t) for i, t in enumerate(case["experiences"].values())]
    assert render.batch_table(records, case["operations"]) == case["text"]


@pytest.mark.parametrize("gt", [True, False])
def test_partial_filter(gt):
    """Сводки только у групп, где верна часть попыток (без метки — у всех); попытка без траектории выпадает до
    подсчёта."""
    want = MEMORY["partial_filter"][f"given_ground_truth={gt}"]
    groups = {c: group(c, r, target="42" if gt else "") for c, r in want["rewards"].items()}
    groups["notraj"] = group("notraj", [0, 1, 0], target="42" if gt else "",
                             output=lambda c, i, r: "" if i == 0 else trajectory(c, i, r))
    summarized = {}
    for c, g in groups.items():
        model = Fake(answer=lambda user: "summary" if user.startswith(MARKERS[0]) else "<Experiences>\n1. X\n</Experiences>")
        T.Contrast()(Ex(model), g, library([]))
        rewards = [float(e.ok) for e in T.rollouts(g, False)]
        n = sum(stage(call["user"]) == 0 for call in model.calls)
        if n:
            summarized[g.question] = rewards[:n]
    assert summarized == want["summarized"]


def test_empty_summary_kept():
    """Пустая сводка остаётся в группе (у апстрима выпадает только исключение); нет ответа — выпадает."""
    for empty, attempts in (("", 2), (None, 0)):
        model = Fake(answer=lambda user: empty if user.startswith(MARKERS[0]) else "<Experiences>\n1. X\n</Experiences>")
        T.Contrast()(Ex(model), group("A", [1, 0]), library([]))
        advantage = [c["user"] for c in model.calls if stage(c["user"]) == 1]
        assert len(advantage) == bool(attempts) and all(f"Attempt {i}" in advantage[0] for i in range(1, attempts + 1))

# цикл обновления: два батча подряд


def test_loop():
    """ExperienceUpdater.run на двух батчах: те же запросы в том же порядке (стадии по всему батчу), те же ответы, те
    же опыты G0, G1, ...; все вызовы без параметров запроса (model_params = {})."""
    m = MEM.Library()
    for run in LOOP:
        assert [r.text for r in m.records()] == list(run["before"].values())
        model = Fake(run["requests"])
        m.learn(Ex(model), T.Contrast().batch(Ex(model), [group(c, r) for c, r in run["rewards"].items()], m))
        assert [(c["system"], c["user"]) for c in model.calls] == [messages(c) for c in run["requests"]]
        assert all(c["params"] == {} for c in run["requests"]) and all(c["params"] == {} for c in model.calls)
        assert render.experiences(m.records()) == "\n".join(f"[{k}]. {v}" for k, v in run["experiences"].items())

# показ и настройки


def test_show():
    """Итоговый агент: инструкции — ровно итоговый конфиг апстрима (_create_agent_config_with_experiences), T и top_p
    оттуда же; без опытов агент остаётся при температуре rollout (model_copy поверхностный)."""
    cfg = CONFIG["math_reasoning"]
    final = yaml.safe_load(cfg["final_agent_yaml"])
    test = Ex(None)
    test.task, test.training = TASKS["dapo"], False
    p = SHOW.AGENT.prompt(test, library(["Units: check units.", "Verify: recompute."]), {"context": "q"}, 0)
    call = p.solver.call("")
    assert call.messages == [{"role": "system", "content": final["agent"]["instructions"]}, {"role": "user", "content": "q"}]
    settings = final["model"]["model_settings"]
    assert (call.params["temperature"], call.params["top_p"]) == (settings["temperature"], settings["top_p"])
    empty = SHOW.AGENT.prompt(test, library([]), {"context": "q"}, 0).solver.call("")
    assert empty.params["temperature"] == cfg["after_build"]["practice_rollout_temperature"] == SHOW.ROLLOUT_TEMPERATURE


def test_settings():
    """Температуры и размеры из конфига апстрима (math_reasoning.yaml, math_agent.yaml) после build."""
    cfg = CONFIG["math_reasoning"]
    practice, built = cfg["practice"], cfg["after_build"]
    final = yaml.safe_load(cfg["final_agent_yaml"])["model"]["model_settings"]
    at = M.tfgrpo.attempts
    assert at.n == M.GROUP == practice["grpo_n"] == built["practice_pass_k"]
    # температуру и top_p попыток ставит агент (решатель метода), попытки их не меняют
    rollout = Ex(None)
    rollout.task, rollout.training = TASKS["dapo"], True
    sent = [SHOW.AGENT.prompt(rollout, library([]), {"context": "q"}, k).solver.call("").params for k in range(at.n)]
    assert [p["temperature"] for p in sent] == [practice["rollout_temperature"]] * M.GROUP
    assert built["practice_rollout_temperature"] == SHOW.ROLLOUT_TEMPERATURE
    # rollout меняет у агента только температуру: top_p итогового агента у всех попыток
    assert [p["top_p"] for p in sent] == [cfg["loaded"]["agent_top_p"]] * at.n == [SHOW.TOP_P] * at.n
    assert built["original_temperature"] == final["temperature"] == SHOW.TEMPERATURE and final["top_p"] == SHOW.TOP_P
    assert U.NUM == practice["num_experiences_per_query"]
    assert practice["given_ground_truth"] and M.tfgrpo.verdict is verdict.golden
    assert M.tfgrpo.protocol.epochs == practice["epochs"] and not M.tfgrpo.flush and M.tfgrpo.protocol.final
    assert cfg["updater_query_params"] == {}            # обновление без температуры: test_loop
    # eval при обучении делит агента с rollout (T = 0.7): отсюда и итоговый агент без опытов при 0.7 (test_show)
    assert built["practice_and_eval_share_agent"] and built["eval_rollout_temperature"] == SHOW.ROLLOUT_TEMPERATURE
    deviation("S3")             # батч 20 из 40 задач против 50 из 100: те же 2 шага за эпоху
    assert (M.BATCH, practice["batch_size"]) == (20, 50)
