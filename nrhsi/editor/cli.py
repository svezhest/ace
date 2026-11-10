"""CLI писателя: сессия по наблюдениям ревьювера; итог — out/<tag>.diff и out/<tag>.summary.json."""
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
    ap.add_argument("--view", help="вид узла (README.md, src/, logs/), по умолчанию — C.VIEWS[бенч]")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--input", help="тег сессии ревьювера в --rlogs: на вход идут её принятые report")
    src.add_argument("--input-text", help="файл с готовым текстом наблюдений: идёт на вход как есть")
    ap.add_argument("--rlogs", default=C.RLOGS, help="логи сессий ревьювера (для --input)")
    ap.add_argument("--ticket", help="json тикета {change_expected, runs, keep}: ожидание ревьювера — абзац в наблюдении "
                    "и проверка после каждой правки")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--stand", default="default", help="профиль стенда (stands/<имя>.json): модель и генерация")
    ap.add_argument("--home", default=C.HERE, required=C.HERE is None, help="каталог сессий: logs/, out/, work/")
    ap.add_argument("--lint", default=C.LINT, help="каталог с pyflakes (иначе — из окружения)")
    ap.add_argument("--dry", action="store_true", help="напечатать системный промпт и первое сообщение и выйти")
    return ap.parse_args()


def main():
    a = parse_args()
    C.HERE, C.RLOGS, C.LINT = os.path.abspath(a.home), a.rlogs, a.lint
    if a.ticket:
        C.TICKET = json.load(open(a.ticket))
        assert C.TICKET["change_expected"] in ("prompt", "control", "any") and C.TICKET["runs"]
    if not a.view and a.bench not in C.VIEWS:
        raise SystemExit(f"--view is required: no default view for {a.bench}")
    if a.view:
        C.VIEWS[a.bench] = os.path.realpath(os.path.expanduser(a.view))
    view = C.VIEWS[a.bench]
    system = P.system()
    first = IN.first_user(text_path=a.input_text) if a.input_text else IN.first_user(IN.load_reports(a.input))
    if a.dry:
        print(system, "\n-----\n", first)
        return
    F.apply_stand(a.stand)
    src_before = WK.tree_hash(f"{view}/src")
    os.makedirs(f"{C.HERE}/logs", exist_ok=True)
    os.makedirs(f"{C.HERE}/out", exist_ok=True)
    root = WK.build_work(a.bench, a.tag)
    prof = WK.make_profile(root, a.tag)
    end, st, edits = SE.run_session(system, first, root, prof, a.seed * 1000 + 11, f"{C.HERE}/logs/{a.tag}.jsonl")
    assert WK.tree_hash(f"{view}/src") == src_before, "view src changed!"
    with open(f"{C.HERE}/out/{a.tag}.diff", "w") as f:
        f.write(WK.diff_src(a.bench, root))
    summary = {"tag": a.tag, "bench": a.bench, "input": a.input, "input_text": a.input_text, "seed": a.seed, "view": view,
               "ticket": C.TICKET, "bash_limit": C.BASH_LIMIT, "final_turns": C.FINAL_TURNS, "temp": F.TEMP,
               "stand": F.STAND, "view_src_hash": src_before,
               "editor": {"end": end, "stats": st, "src_hash_after": WK.tree_hash(f"{root}/src")}}
    json.dump(summary, open(f"{C.HERE}/out/{a.tag}.summary.json", "w"), ensure_ascii=False, indent=1)
    print(json.dumps({"editor": end, "edits": f"{st['edits_applied']}/{st['edits_attempted']}",
                      "fail": st["edit_fail"], "max_prompt": st["max_prompt"],
                      "min": round(st["model_sec"] / 60, 1)}), flush=True)
