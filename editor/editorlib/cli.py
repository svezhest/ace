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
    ap.add_argument("--bench", choices=list(C.VIEWS), required=True)
    ap.add_argument("--input", required=True, help="тег сессии исследователя (report на входе)")
    ap.add_argument("--arm", choices=["obs", "fix"], required=True)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--view", help="вид узла (src/ и README.md), по умолчанию — корневой вид бенчмарка")
    ap.add_argument("--predict", action="store_true", help="плечо: перед smoke записать ожидаемый вывод, после — сверить")
    ap.add_argument("--stand", default="default", help="профиль стенда (stands/<имя>.json): модель и генерация")
    return ap.parse_args()


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
    if a.dry:
        print(esys, "\n-----\n", first)
        return
    root = WK.build_work(a.bench, a.tag)
    prof = WK.make_profile(root, a.tag)
    end, st, edits = SE.run_session("editor", esys, first, root, prof, a.seed * 1000 + 11,
                                    f"{C.HERE}/logs/{a.tag}.jsonl")
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
    if a.view:
        C.VIEWS[a.bench] = os.path.realpath(os.path.expanduser(a.view))
    if not a.dry:
        F.apply_stand(a.stand)
    reports = IN.load_reports(a.input)
    src_before = WK.tree_hash(f"{C.VIEWS[a.bench]}/src")
    os.makedirs(f"{C.HERE}/logs", exist_ok=True)
    os.makedirs(f"{C.HERE}/out", exist_ok=True)
    summary = {"tag": a.tag, "bench": a.bench, "input": a.input, "arm": a.arm, "seed": a.seed,
               "view": C.VIEWS[a.bench], "predict": a.predict, "stand": F.STAND,
               "n_reports": len(reports), "view_src_hash": src_before}
    if a.arm == "fix":
        props = propose_step(a, reports, src_before, summary)
        if not props:
            return
        first = IN.first_user_editor_fix(props)
    else:
        first = IN.first_user_editor_obs(reports)
    editor_step(a, first, src_before, summary)
