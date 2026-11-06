"""CLI редактора: плечо fix — шаг вариантов (proposer), затем редактор; итог в out/<tag>.diff и out/<tag>.summary.json."""
import argparse
import json
import os

from .cfg import F
from . import cfg as C
from . import prompt as P
from . import inputs as IN
from . import work as WK
from . import session as SE


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bench", choices=list(C.BENCHES), required=True)
    ap.add_argument("--input", help="тег сессии исследователя (report на входе); не нужен для --arm merge")
    ap.add_argument("--arm", choices=["obs", "fix", "merge"], required=True,
                    help="merge: комбинатор, --view — вид editor/merge3.py --markers")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--view", help="вид узла (src/ и README.md), по умолчанию — корневой вид бенчмарка")
    ap.add_argument("--predict", action="store_true", help="плечо: перед smoke записать ожидаемый вывод, после — сверить")
    ap.add_argument("--cite", action="store_true", help="под каждым наблюдением — цитированные им строки логов, как в файле")
    ap.add_argument("--import-src", action="store_true", help="строка в Tools: модули src/ импортируются из python3")
    ap.add_argument("--smoke-calls", action="store_true", help="smoke: вызовы функций harness/hooks, аргументы, исключения")
    ap.add_argument("--input-text", help="плечо obs: вместо наблюдений --input — текст из этого файла как есть")
    ap.add_argument("--rerun", action="store_true", help="в копии logs/ вида и tests/rerun.py: повтор записанных прогонов на src/")
    ap.add_argument("--goal-text", help="якорь цели: текст файла дописывается к последнему выводу инструмента каждого хода")
    ap.add_argument("--goal-k", type=int, default=0, help="когда осталось K вызовов bash — цель: проверить последние правки")
    ap.add_argument("--rerun-at", action="store_true", help="с --rerun: в README — rerun.py N --at K (настоящие значения на шаге)")
    ap.add_argument("--finish-review", action="store_true", help="первый finish показывает diff всех правок и вывод rerun")
    ap.add_argument("--checked", action="store_true", help="после конца bash правки не применяются (их нечем проверить)")
    ap.add_argument("--stages", help="R,K: R bash на чтение; первая правка (или конец R) — ещё K bash на проверку; "
                    "потом правки не применяются (включает --checked)")
    ap.add_argument("--auto-check", action="store_true", help="каждая применённая правка — pyflakes, smoke, rerun в ответе edit")
    ap.add_argument("--rerun-tool", action="store_true", help="с --rerun: rerun — инструмент rerun(change, run), ok/failed по ожиданию")
    ap.add_argument("--scratch", action="store_true", help="каталог scratch/ копии, куда можно писать")
    ap.add_argument("--tools-dir", default="tests", help="5.11: каталог rerun/smoke в копии (tests, tools, __tools)")
    ap.add_argument("--hide-tools", action="store_true", help="5.11: исходников rerun/smoke в копии нет; это команды")
    ap.add_argument("--intent-opt", action="store_true", help="5.11: как --intent, но поля необязательны")
    ap.add_argument("--ask-changed", action="store_true", help="5.11, с --auto-check --rerun: вопрос про изменившиеся удачные прогоны")
    ap.add_argument("--plan-line", action="store_true", help="5.11: строка «до правки опиши, как пойдёт прогон тикета»")
    ap.add_argument("--broad-example", action="store_true", help="5.11: пример правки шире задуманного (выдуманный репозиторий)")
    ap.add_argument("--nav-v", type=int, default=1, help="5.11: вариант примера навигатора (1, 2)")
    ap.add_argument("--intent", action="store_true", help="5.11, с --auto-check --rerun: edit(…, expect_runs, expect); сверка с изменившимися прогонами")
    ap.add_argument("--navigator", action="store_true", help="5.11: в системном промпте пример прицельного поиска (выдуманный репозиторий)")
    ap.add_argument("--given-files", action="store_true", help="5.11, абляция, с --input-text: README.md и все файлы src/ целиком")
    ap.add_argument("--given-code", action="store_true", help="5.11, с --input-text: под текстом — код src/ вида по его ссылкам")
    ap.add_argument("--ticket", help="6.11, с --auto-check --rerun: json тикета {change_expected, runs} — скрытое ожидание ревьювера")
    ap.add_argument("--ticket-cover", action="store_true", help="6.11, с --ticket: после строки проверки — сколько раз выполнились изменённые строки src в прогоне тикета")
    ap.add_argument("--ticket-ret", action="store_true", help="6.11, с --ticket-cover: у строк return правки — что они вернули в прогоне тикета")
    ap.add_argument("--ticket-first", action="store_true", help="6.11, с --ticket: проверка по тикету — первой в выводе после правки")
    ap.add_argument("--ticket-line", action="store_true", help="6.11, с --ticket: в строке Failed — какое изменённое условие выполнялось и ни разу не было истинным")
    ap.add_argument("--ticket-why", action="store_true", help="6.11, с --ticket-values: перекрытый def (по прогону), форма длинных строк; факт и к Failed «только тексты»")
    ap.add_argument("--ticket-passed", action="store_true", help="6.11, с --ticket-values: первый задетый удачный прогон — где расходится и какие изменённые условия сработали")
    ap.add_argument("--ticket-anchor", action="store_true", help="6.11, с --ticket-why: к значениям — строка лога с ответом модели")
    ap.add_argument("--ticket-values", action="store_true", help="6.11, с --ticket-line: значения операндов названного условия на его последнем выполнении")
    ap.add_argument("--ticket-show", action="store_true", help="6.11, с --ticket: ожидание ревьювера — строкой в наблюдении (писатель видит)")
    ap.add_argument("--resume", help="6.11: лог сессии писателя; история до --resume-turn, этот ход исполняется заново")
    ap.add_argument("--resume-turn", type=int)
    ap.add_argument("--resume-bash", type=int, default=15, help="сколько bash добавить с хода воскрешения")
    ap.add_argument("--bash-limit", type=int, help="число вызовов bash вместо cfg.BASH_LIMIT (бюджет всех вызовов растёт с ним)")
    ap.add_argument("--temp", type=float, help="температура писателя вместо температуры агентов из профиля стенда")
    ap.add_argument("--stand", default="default", help="профиль стенда (stands/<имя>.json): модель и генерация")
    ap.add_argument("--home", default=C.HERE, required=C.HERE is None, help="каталог сессий: logs/, out/, work/")
    ap.add_argument("--rlogs", default=C.RLOGS, help="логи сессий исследователя (кроме --arm merge)")
    ap.add_argument("--lint", default=C.LINT, help="каталог с pyflakes (иначе — из окружения)")
    return ap.parse_args()


TICKET_TASK = "\n\nChange src/ so that the agent fails fewer tasks."


def ticket_line(first, t):
    """6.11 --ticket-show: ожидание ревьювера — абзацем в конце наблюдения, перед задачей."""
    rs = t["runs"]
    runs = f"run {rs[0]}" if len(rs) == 1 else "runs " + ", ".join(map(str, rs[:-1])) + f" and {rs[-1]}"
    line = {"control": f"Change expected: control — what the harness code does in {runs} should change, not only the texts the model reads.",
            "prompt": f"Change expected: prompt — the texts the model reads in {runs} should change.",
            "any": f"Change expected: any — {runs} should go differently, through the texts the model reads or through the harness code."}[t["change_expected"]]
    assert first.count(TICKET_TASK) == 1, "task line not found"
    return first.replace(TICKET_TASK, "\n\n" + line + TICKET_TASK)


def save_summary(tag, summary):
    json.dump(summary, open(f"{C.HERE}/out/{tag}.summary.json", "w"), ensure_ascii=False, indent=1)


def propose_step(a, reports, src_before, summary):
    """Шаг вариантов -> предложения ([] — редактор пропущен, summary записан); --dry — промпты и заглушка."""
    psys, pfirst = P.fill(P.PROPOSER_T), IN.first_user_proposer(reports)
    if a.dry:
        print(psys, "\n-----\n", pfirst, "\n=====")
        return [{"problem": "<problem>", "fix": "<fix>"}]
    proot = WK.build_work(a.bench, a.tag + "_p", smoke=False)
    pprof = WK.make_profile(proot, a.tag + "_p")
    pend, pst, props = SE.run_session("proposer", psys, pfirst, proot, pprof, a.seed * 1000 + 7,
                                      f"{C.HERE}/logs/{a.tag}_p.jsonl", n_obs=len(reports))
    assert WK.tree_hash(f"{proot}/src") == src_before, "proposer copy changed"
    summary["proposer"] = {"end": pend, "stats": pst, "n": len(props)}
    print(json.dumps({"proposer": pend, "proposals": len(props), "max_prompt": pst["max_prompt"],
                      "min": round(pst["model_sec"] / 60, 1)}), flush=True)
    if not props:
        summary["editor"] = {"end": "skipped: no proposals"}
        save_summary(a.tag, summary)
    return props


def editor_step(a, first, src_before, summary):
    esys = P.fill(P.EDITOR_T, a.arm)
    if a.predict:
        esys = esys.replace(P.CHECK_LINE, P.PREDICT_LINE)
        assert P.PREDICT_LINE in esys
    if a.import_src:
        esys = esys.replace(F.PYTHON_LINE, F.PYTHON_LINE + "\n" + F.IMPORT_LINE)
        assert F.IMPORT_LINE in esys
    if a.rerun:
        for old, new in (P.RERUN_REPO, P.RERUN_ARM, (P.CHECK_LINE, P.RERUN_CHECK_LINE)):
            assert old in esys, old
            esys = esys.replace(old, new)
    if a.rerun_at:
        esys = esys.replace(P.RERUN_CHECK_LINE, P.RERUN_CHECK_LINE + P.RERUN_AT_LINE)
        assert P.RERUN_AT_LINE in esys
    if a.finish_review:
        assert a.rerun and P.FINISH_LINE in esys, "--finish-review needs --rerun"
        esys = esys.replace(P.FINISH_LINE, P.FINISH_REVIEW_LINE)
    if a.checked:
        esys = esys.replace(P.fill(P.LIMIT_LINE), P.fill(P.CHECKED_LIMIT_LINE))
        assert P.fill(P.CHECKED_LIMIT_LINE) in esys
    if a.stages:
        line = P.STAGES_LINE.replace("STAGE_R", str(C.STAGES[0])).replace("STAGE_K", str(C.STAGES[1]))
        esys = esys.replace(P.fill(P.CHECKED_LIMIT_LINE), line)
        assert line in esys
    if a.rerun_tool:
        for old, new in ((P.RERUN_CHECK_LINE, P.RERUN_TOOL_CHECK_LINE), (P.EDIT_TOOL_LINE, P.EDIT_TOOL_LINE + "\n" + P.RERUN_TOOL_LINE),
                         ("what python3 tests/rerun.py prints on them", "what rerun prints on them")):
            if old in esys or old.startswith("what"):
                esys = esys.replace(old, new)
        assert P.RERUN_TOOL_LINE in esys and P.RERUN_TOOL_CHECK_LINE in esys and "tests/rerun.py" not in esys
    if a.auto_check:
        chk = next(x for x in (P.RERUN_TOOL_CHECK_LINE, P.RERUN_CHECK_LINE, P.CHECK_LINE) if x in esys)
        add = P.AUTO_CHECK_LINE.replace("RERUN_NAME", "rerun" if a.rerun_tool else "python3 tests/rerun.py")
        if not a.rerun:
            add = add.replace(", python3 tests/smoke.py and python3 tests/rerun.py", " and python3 tests/smoke.py")
        esys = esys.replace(chk, chk + add)
    if a.intent_opt:
        a.intent = True
    if a.ask_changed:
        assert a.auto_check and a.rerun and not a.rerun_tool, "--ask-changed needs --auto-check --rerun"
    if a.intent:
        assert a.auto_check and a.rerun and not a.rerun_tool, "--intent needs --auto-check --rerun"
        assert P.EDIT_TOOL_LINE in esys
        sig = "expect_runs?, expect?" if a.intent_opt else "expect_runs, expect"
        esys = esys.replace(P.EDIT_TOOL_LINE, P.EDIT_TOOL_LINE.replace("- edit(path, old_string, new_string)",
                            f"- edit(path, old_string, new_string, {sig})") + (P.INTENT_OPT_LINE if a.intent_opt else P.INTENT_LINE))
    if a.scratch:
        esys = esys.replace(P.SCRATCH_NOWRITE, P.SCRATCH_WRITE).replace("a read-only shell in", "a shell in").replace(
            F.PYTHON_LINE, F.PYTHON_SCRATCH_LINE.replace("SCRATCH/", F.SCRATCH_DIR + "/"))
        assert P.SCRATCH_WRITE in esys and "read-only shell" not in esys
    if a.navigator:
        assert "\n# How to work\n" in esys
        esys = esys.replace("\n# How to work\n", "\n" + (P.NAV_EXAMPLE2 if a.nav_v == 2 else P.NAV_EXAMPLE) + "\n\n# How to work\n")
    if a.broad_example:
        assert a.rerun and "\n# How to work\n" in esys
        esys = esys.replace("\n# How to work\n", "\n" + P.BROAD_EXAMPLE + "\n\n# How to work\n")
    if a.plan_line:
        assert "\n# How to work\n" in esys
        esys = esys.replace("\n# How to work\n", "\n# How to work\n" + P.PLAN_LINE + "\n")
    esys = WK.tt(esys)        # 5.11 --tools-dir / --hide-tools
    if a.dry:
        print(esys, "\n-----\n", first)
        return
    root = WK.build_work(a.bench, a.tag)
    prof = WK.make_profile(root, a.tag)
    resume = None
    if a.resume:
        from . import resume as RS
        recs = RS.load(a.resume)
        print(json.dumps({"resume_edits_replayed": RS.apply_edits(recs, a.resume_turn, root)}), flush=True)
        resume = RS.restorer(recs, a.resume_turn, a.resume_bash)
        summary["resume"] = {"log": a.resume, "turn": a.resume_turn, "bash": a.resume_bash}
    end, st, edits = SE.run_session("editor", esys, first, root, prof, a.seed * 1000 + 11,
                                    f"{C.HERE}/logs/{a.tag}.jsonl", resume=resume)
    assert WK.tree_hash(f"{C.VIEWS[a.bench]}/src") == src_before, "view src changed!"
    d = WK.diff_src(a.bench, root)
    with open(f"{C.HERE}/out/{a.tag}.diff", "w") as f:
        f.write(d)
    summary["editor"] = {"end": end, "stats": st, "src_hash_after": WK.tree_hash(f"{root}/src")}
    save_summary(a.tag, summary)
    print(json.dumps({"editor": end, "edits": f"{st['edits_applied']}/{st['edits_attempted']}",
                      "fail": st["edit_fail"], "max_prompt": st["max_prompt"],
                      "min": round(st["model_sec"] / 60, 1)}), flush=True)


def main():
    a = parse_args()
    C.HERE, C.RLOGS, C.LINT, C.CHECKED, C.SMOKE_CALLS, C.RERUN, C.GOAL_K = (
        os.path.abspath(a.home), a.rlogs, a.lint, a.checked, a.smoke_calls, a.rerun, a.goal_k)
    C.RERUN_AT, C.FINISH_REVIEW = a.rerun_at, a.finish_review
    if a.bash_limit:
        C.BASH_LIMIT, C.STEP_BUDGET = a.bash_limit, max(C.STEP_BUDGET, a.bash_limit + 35)
    if a.stages:
        C.STAGES = tuple(int(x) for x in a.stages.split(","))
        assert len(C.STAGES) == 2 and not a.bash_limit and not a.goal_k, "--stages R,K; без --bash-limit и --goal-k"
        C.BASH_LIMIT, a.checked, C.CHECKED = sum(C.STAGES), True, True   # C.CHECKED уже выставлен выше — ставим и его
        C.STEP_BUDGET = max(C.STEP_BUDGET, C.BASH_LIMIT + 35)
    assert not a.rerun_tool or (a.rerun and not a.rerun_at), "--rerun-tool needs --rerun, not with --rerun-at"
    C.AUTO_CHECK, C.RERUN_TOOL, C.SCRATCH = a.auto_check, a.rerun_tool, a.scratch
    C.INTENT, C.INTENT_OPT, C.ASK_CHANGED = a.intent or a.intent_opt, a.intent_opt, a.ask_changed
    assert not (a.hide_tools or a.tools_dir != "tests") or not a.rerun_tool, "--tools-dir/--hide-tools без --rerun-tool"
    C.TOOLS_DIR, C.HIDE_TOOLS = a.tools_dir, a.hide_tools
    if a.ticket:
        assert a.auto_check and a.rerun, "--ticket needs --auto-check --rerun"
        C.TICKET = json.load(open(a.ticket))
        assert C.TICKET["change_expected"] in ("prompt", "control", "any") and C.TICKET["runs"]
    assert a.ticket or not a.ticket_cover, "--ticket-cover needs --ticket"
    C.TICKET_COVER = a.ticket_cover
    assert a.ticket_cover or not a.ticket_ret, "--ticket-ret needs --ticket-cover"
    C.TICKET_RET = a.ticket_ret
    assert a.ticket or not a.ticket_first, "--ticket-first needs --ticket"
    C.TICKET_FIRST = a.ticket_first
    assert a.ticket or not a.ticket_line, "--ticket-line needs --ticket"
    C.TICKET_LINE = a.ticket_line
    assert a.ticket_line or not a.ticket_values, "--ticket-values needs --ticket-line"
    C.TICKET_VALUES = a.ticket_values
    assert a.ticket_values or not a.ticket_why, "--ticket-why needs --ticket-values"
    C.TICKET_WHY = a.ticket_why
    assert a.ticket_values or not a.ticket_passed, "--ticket-passed needs --ticket-values"
    C.TICKET_PASSED = a.ticket_passed
    assert a.ticket_why or not a.ticket_anchor, "--ticket-anchor needs --ticket-why"
    C.TICKET_ANCHOR = a.ticket_anchor
    if a.hide_tools:
        C.HIDDEN = f"{os.path.abspath(a.home)}/work/.tools_{a.tag}"
    F.SCRATCH = a.scratch            # 4.11: механика scratch/ исследователя — и у писателя
    assert not a.rerun_at or a.rerun, "--rerun-at needs --rerun"
    C.GOAL_TEXT = open(a.goal_text).read().strip() if a.goal_text else None
    if not a.view and a.bench not in C.VIEWS:
        raise SystemExit(f"--view is required: no default view for {a.bench}")
    if a.view:
        C.VIEWS[a.bench] = os.path.realpath(os.path.expanduser(a.view))
    if not a.dry:
        F.apply_stand(a.stand)
        if a.temp is not None:
            F.TEMP = a.temp
    if (a.arm == "merge") == bool(a.input and a.rlogs):
        raise SystemExit("--input and --rlogs are needed for obs/fix and not for merge")
    reports = [] if a.arm == "merge" else IN.load_reports(a.input)
    src_before = WK.tree_hash(f"{C.VIEWS[a.bench]}/src")
    os.makedirs(f"{C.HERE}/logs", exist_ok=True)
    os.makedirs(f"{C.HERE}/out", exist_ok=True)
    summary = {"tag": a.tag, "bench": a.bench, "input": a.input, "arm": a.arm, "seed": a.seed,
               "view": C.VIEWS[a.bench], "predict": a.predict, "cite": a.cite, "import_src": a.import_src,
               "checked": a.checked, "smoke_calls": a.smoke_calls, "rerun": a.rerun, "rerun_at": a.rerun_at, "finish_review": a.finish_review, "goal_k": a.goal_k, "stages": a.stages, "auto_check": a.auto_check, "rerun_tool": a.rerun_tool, "scratch": a.scratch, "tools_dir": a.tools_dir, "hide_tools": a.hide_tools, "given_code": a.given_code, "given_files": a.given_files, "navigator": a.navigator, "intent": a.intent or a.intent_opt, "intent_opt": a.intent_opt, "ask_changed": a.ask_changed, "plan_line": a.plan_line, "broad_example": a.broad_example, "nav_v": a.nav_v, "ticket": C.TICKET, "bash_limit": C.BASH_LIMIT, "goal_text": a.goal_text, "temp": F.TEMP, "input_text": a.input_text, "stand": F.STAND,
               "n_reports": len(reports), "view_src_hash": src_before}
    if a.arm == "fix":
        props = propose_step(a, reports, src_before, summary)
        if not props:
            return
        first = IN.first_user_editor_fix(props)
    elif a.arm == "merge":
        first = IN.first_user_merge(C.VIEWS[a.bench])
    elif a.input_text:
        first = IN.first_user_editor_text(a.input_text, f"{C.VIEWS[a.bench]}/src" if a.given_code or a.given_files else None,
                                          files=a.given_files)
    else:
        first = IN.first_user_editor_obs(reports, IN.review_root(a.input) if a.cite else None)
    if a.ticket_show:
        assert C.TICKET, "--ticket-show needs --ticket"
        first = ticket_line(first, C.TICKET)
    summary["ticket_show"] = a.ticket_show
    summary["ticket_cover"] = a.ticket_cover
    summary["ticket_ret"] = a.ticket_ret
    summary["ticket_first"] = a.ticket_first
    summary["ticket_line"] = a.ticket_line
    summary["ticket_values"] = a.ticket_values
    summary["ticket_why"] = a.ticket_why
    summary["ticket_passed"] = a.ticket_passed
    summary["ticket_anchor"] = a.ticket_anchor
    editor_step(a, first, src_before, summary)
