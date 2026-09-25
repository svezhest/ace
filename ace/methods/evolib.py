"""EvoLib (EvoLib/EvoLib/evolib_agent.py, вариант HMMT из eval_main.py: без синтетических тестов).
Промпты ace/prompts/evolib_*.j2: апстрим, из которого убрано только «math».

    1 память      skills (Skill): подзадача целиком (<subtask> с description, solution, result), ig, список fig
                  и doc; insights (Insight) «If ..., then ...», список fig; скрыто от решателя — лучшее решение
                  каждой задачи (Solution)
    2 инжект      choose: одно случайное число на попытку — p < 0.4 sample до 10 skills, p < 0.7 до 10 insights,
                  иначе ничего; выборка с возвращением по весу
    3 сигнал      без метки: попытка верна, если её ответ совпал с ответом большинства
    4 обновление  reflect: seq(ранжирование и IG = log_gain, maybe(insight из лучшего решения; баллы пополам),
                  улучшение по задаче, maybe(сравнение двух решений моделью), skills из ответа, future_gain);
                  curate: consolidate insight и skills (косинус > 0.8 по условию или description, слияние моделью),
                  лучшее решение задачи в best, Future IG в записи
    решатель      3 попытки при T=0, в зачёт ответ большинства; решение разбито на подзадачи (Solver.hint)

Эпох в апстриме тысячи (5000 итераций по кругу), у нас это параметр протокола EPOCHS.
"""
from .. import curate, inject, prompts, reflect
from ..feedback import Feedback
from ..loop import Method, Solver, swap
from ..memory import Insight, Kind, Skill, Solution
from ..update import Update, ask, maybe, seq

P = {n: prompts.load(f"evolib_{n}") for n in ("insight", "merge_skills", "merge_insights", "compare")}

# 1. память

MEMORY = {"skill": Kind(Skill, ("add", "delete")), "insight": Kind(Insight, ("add", "delete")),   # delete только при слиянии
          "best": Kind(Solution, ("add", "edit"), private=True, ids="b")}

# 2. инжект

K, W_IG, EPS = 10, 1.0, 0.01
P_SKILLS, P_INSIGHTS = 0.4, 0.7     # накопленные вероятности веток показа
WEIGHT = inject.gain_weight(W_IG, EPS)

sample = inject.choose(
    (P_SKILLS, inject.show(("skill",), pick=inject.sample(K, WEIGHT), line=inject.plain, head="",
                      before=prompts.text("evolib_skills_intro"))),
    (P_INSIGHTS, inject.show(("insight",), pick=inject.sample(K, WEIGHT), line=inject.plain, head="",
                      before=prompts.text("evolib_insights_intro"))))

# 4. обновление

SIM, RATE = 0.8, 0.5

compare = ask(P["compare"], reflect.compare_fields, then=reflect.second_better)


def attempts(evaluated=False):
    """evaluated: баллы попыток дала внешняя оценка (метка или судья), как синтетические тесты
    в кодовых задачах апстрима: тогда insight только при неудаче лучшей попытки и без деления баллов."""
    insight = ask(P["insight"], reflect.insight_fields(evaluated), then=reflect.with_insight(evaluated))
    return seq(reflect.rank(EPS), maybe(reflect.insight_needed(evaluated), insight), reflect.improving,
               maybe(reflect.disputed(evaluated), compare), reflect.finish(EPS))


library = curate.each(curate.gains(curate.add_insight(P["merge_insights"], SIM), curate.add_skill(P["merge_skills"], SIM, RATE)))

# решатель

SAMPLES = 2                 # ещё попыток: всего 3, ответ большинством

SUBTASKS = prompts.text("evolib_subtasks")

evolib = Method("evolib", MEMORY, sample, Feedback("majority"), Update(attempts(), library),
                Solver(samples=SAMPLES, temperature=0, vote=True, hint=SUBTASKS))
evolib_judge = swap(evolib, "evolib_judge", feedback=Feedback("judge"), reflect=attempts(evaluated=True))
