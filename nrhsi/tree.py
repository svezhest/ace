"""Цикл NRHSI: замер узла -> исследование провалов -> правки (пул детей узла) -> замер ребёнка -> выбор узла.

  python -m nrhsi.tree alfworld --out runs/tree1 --m 40 --k 5 --s 3 --children 10

Узел — вид: README.md, src/ и логи замера на M свежих случайных задачах train (logs/run_N.jsonl, logs/results.jsonl;
раннер бенча <bench>/runner/run.py --out). Корень — стартовый харнесс (tools/make_start.py). Пул узла — S кандидатов:
S сессий исследователя (nrhsi.researcher, политика final) по K провалам, каждая -> редактор (nrhsi.editor, плечо obs)
-> правленая копия src/. Каждый раз развивается узел с лучшей долей ok, у которого есть что взять: неисследованный
или с непустым пулом. Плохой ребёнок не сдвигает родителя: следующим берётся другой кандидат из пула того же узла.
Состояние — OUT/tree.json, запуск возобновляем. Роли и замер — отдельные процессы (у ролей настройки модульные).

OUT/<узел>/ — вид узла и прогон раннера; OUT/<узел>.research/<j>/ — logs/, views/ сессии исследователя;
OUT/<узел>.edit/<j>/ — logs/, out/, work/<tag>/ (README.md + src/ — кандидат) сессии редактора.
"""
import argparse
import glob
import json
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import make_start  # noqa: E402

SHORT = {"alfworld": "alf", "appworld": "app"}   # имя бенча у редактора


def measure(a, view, out, seed):
    """Замер src/ вида view: M случайных задач train -> доля ok; out — вид узла (README.md, src/, logs/)."""
    if not os.path.exists(f"{out}/summary.json"):
        subprocess.run([a.bench_py, f"{ROOT}/{a.bench}/runner/run.py", "--view", view, "--out", out,
                        "--tag", os.path.basename(out), "--split", "train", "--n", str(a.m), "--seed", str(seed),
                        "--workers", str(a.workers), "--stand", a.stand, "--no-publish"], check=True)
        shutil.copy(f"{ROOT}/start/{a.bench}.README.md", f"{out}/README.md")
    s = json.load(open(f"{out}/summary.json"))
    return s["ok"] / s["n"]


def role(*args):
    subprocess.run([sys.executable, "-m", *args], cwd=ROOT, check=True)


def research(a, node, home, tag, seed):
    """Сессия исследователя по K провалам узла -> принятые report."""
    if not glob.glob(f"{home}/logs/*_{tag}.jsonl"):
        role("nrhsi.researcher", "--home", home, "--view", node, "--k", str(a.k), "--seed", str(seed),
             "--policy", "final", "--stand", a.stand, "--tag", tag)
    log, = glob.glob(f"{home}/logs/*_{tag}.jsonl")
    end = [json.loads(x) for x in open(log) if '"type": "end"' in x][-1]
    return end["reports"]


def edit(a, node, rhome, home, tag, seed):
    """Сессия редактора по report сессии tag -> (вид кандидата: README.md + src/, число применённых правок)."""
    summ = f"{home}/out/{tag}.summary.json"
    if not os.path.exists(summ):
        role("nrhsi.editor", "--home", home, "--rlogs", f"{rhome}/logs", "--bench", SHORT[a.bench], "--view", node,
             "--input", tag, "--arm", "obs", "--seed", str(seed), "--stand", a.stand, "--tag", tag,
             *(["--lint", a.lint] if a.lint else []))
    s = json.load(open(summ))
    return f"{home}/work/{tag}", s["editor"]["stats"]["edits_applied"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("bench", choices=sorted(SHORT))
    ap.add_argument("--out", required=True)
    ap.add_argument("--m", type=int, default=40, help="задач на замер узла")
    ap.add_argument("--k", type=int, default=5, help="проваленных трасс на сессию исследователя")
    ap.add_argument("--s", type=int, default=3, help="сессий исследователя (= кандидатов) на узел")
    ap.add_argument("--children", type=int, default=10, help="сколько детей замерить")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--stand", default="default", help="профиль стенда (stands/<имя>.json) для замера и ролей")
    ap.add_argument("--workers", type=int, default=2, help="эпизодов замера параллельно")
    ap.add_argument("--bench-py", help="python с зависимостями бенчмарка (по умолчанию <bench>/.venv/bin/python)")
    ap.add_argument("--lint", help="каталог с pyflakes для редактора (иначе — из окружения)")
    a = ap.parse_args()
    a.bench_py = a.bench_py or f"{ROOT}/{a.bench}/.venv/bin/python"
    out = os.path.realpath(a.out)
    path = f"{out}/tree.json"
    tree = json.load(open(path)) if os.path.exists(path) else {"nodes": {}}
    nodes = tree["nodes"]

    def save():
        json.dump(tree, open(path + ".tmp", "w"), indent=1)
        os.replace(path + ".tmp", path)

    def add_node(nid, parent, view):
        score = measure(a, view, f"{out}/{nid}", a.seed * 100_000 + len(nodes))   # свежие задачи на каждый замер
        nodes[nid] = {"parent": parent, "score": score, "pool": None}
        save()
        print(f"{nid}: {score:.3f} (parent {parent})", flush=True)

    os.makedirs(out, exist_ok=True)
    if "n0" not in nodes:
        if not os.path.isdir(f"{out}/start"):
            make_start.make_view(a.bench, f"{out}/start")
        add_node("n0", None, f"{out}/start")
    while len(nodes) - 1 < a.children:
        open_ = [n for n, v in nodes.items() if v["pool"] is None or v["pool"]]
        if not open_:
            print("all pools are empty")
            break
        nid = max(open_, key=lambda n: nodes[n]["score"])
        node = nodes[nid]
        if node["pool"] is None:                              # исследовать узел: S сессий -> S кандидатов
            node["pool"] = []
            for j in range(a.s):
                tag, seed = f"{nid}_{j}", a.seed * 1000 + j
                rhome = f"{out}/{nid}.research/{j}"
                if not research(a, f"{out}/{nid}", rhome, tag, seed):
                    continue
                view, applied = edit(a, f"{out}/{nid}", rhome, f"{out}/{nid}.edit/{j}", tag, seed)
                if applied:
                    node["pool"].append(view)
            save()
            continue
        child = f"n{len(nodes)}"
        add_node(child, nid, node["pool"].pop(0))
        save()
    # TODO слияние узлов разных веток (D2) — второй поставщик правок, условия не решены
    best = max(nodes, key=lambda n: nodes[n]["score"])
    print(f"best: {best} {nodes[best]['score']:.3f}")


if __name__ == "__main__":
    main()
