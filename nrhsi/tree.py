"""Цикл NRHSI: замер узла -> исследование провалов -> правки (пул детей узла) -> замер ребёнка -> выбор узла.

  python nrhsi/tree.py alfworld --out runs/tree1 --m 40 --k 5 --s 3 --children 10

Узел — вариант src/ и его замер на M свежих случайных задачах (bench/run.py). Пул узла — S кандидатов:
S сессий исследователя по K провалам, каждая -> редактор -> правленая копия src/. Каждый раз развивается узел
с лучшей долей ok, у которого есть что взять: неисследованный или с непустым пулом. Плохой ребёнок не сдвигает
родителя: следующим берётся другой кандидат из пула того же узла. Состояние — OUT/tree.json, запуск возобновляем.
"""
import argparse
import json
import os
import subprocess
import sys

import editor
import researcher

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BENCH_PY = os.environ.get("NRHSI_BENCH_PY", sys.executable)    # python с зависимостями бенчмарка


def measure(bench, src, out, m, seed):
    if not os.path.exists(f"{out}/summary.json"):
        subprocess.run([BENCH_PY, f"{ROOT}/bench/run.py", bench, "--src", src, "--out", out, "--n", str(m),
                        "--seed", str(seed)], check=True)
    s = json.load(open(f"{out}/summary.json"))
    return s["ok"] / s["n"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("bench", choices=["alfworld", "appworld"])
    ap.add_argument("--out", required=True)
    ap.add_argument("--m", type=int, default=40, help="задач на замер узла")
    ap.add_argument("--k", type=int, default=5, help="проваленных трасс на сессию исследователя")
    ap.add_argument("--s", type=int, default=3, help="сессий исследователя (= кандидатов) на узел")
    ap.add_argument("--children", type=int, default=10, help="сколько детей замерить")
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()
    out = os.path.realpath(a.out)
    readme = f"{ROOT}/bench/{a.bench}/view_readme.md"
    path = f"{out}/tree.json"
    tree = json.load(open(path)) if os.path.exists(path) else {"nodes": {}}
    nodes = tree["nodes"]

    def save():
        json.dump(tree, open(path + ".tmp", "w"), indent=1)
        os.replace(path + ".tmp", path)

    def add_node(nid, parent, src):
        d = f"{out}/{nid}"
        score = measure(a.bench, src, d, a.m, a.seed * 100_000 + len(nodes))   # свежие задачи на каждый замер
        nodes[nid] = {"parent": parent, "score": score, "pool": None}
        save()
        print(f"{nid}: {score:.3f} (parent {parent})", flush=True)

    os.makedirs(out, exist_ok=True)
    if "n0" not in nodes:
        add_node("n0", None, f"{ROOT}/bench/{a.bench}/src")
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
                r = f"{out}/{nid}.research/{j}"
                reports = researcher.run(f"{out}/{nid}", readme, a.k, a.seed * 1000 + j, r) \
                    if not os.path.exists(f"{r}/reports.json") else json.load(open(f"{r}/reports.json"))["reports"]
                if not reports:
                    continue
                e = f"{out}/{nid}.edit/{j}"
                src, applied = editor.run(f"{out}/{nid}/src", readme, reports, e, a.seed * 1000 + j) \
                    if not os.path.exists(f"{e}/edits.json") else \
                    (f"{e}/work/src", sum(x["applied"] for x in json.load(open(f"{e}/edits.json"))["edits"]))
                if applied:
                    node["pool"].append(src)
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
