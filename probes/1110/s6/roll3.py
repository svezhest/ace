"""Шаг 6 тикета 10.11: первые три хода писателя на базе (V = 0) или на варианте постановки (A, B, C).
python3 probes/1110/s6/roll3.py V NN HOME_DIR [N]   — прокат editor/roll.py с хода 1 на три хода, стенд default.
Пары --sub берутся из runs/fk_1110/s6/V/NN.sub.json (probes/1110/s6/variants.py).
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
VIEW = {"05": ("app", "app_r4"), "06": ("alf", "alf_r1"), "08": ("alf", "alf_r1"), "09": ("app", "app_n2")}
v, nn, home = sys.argv[1:4]
n = sys.argv[4] if len(sys.argv) > 4 else "10"
d, t = f"{ROOT}/runs/fk_1110/s6", f"{ROOT}/runs/typed_1110"
os.makedirs(f"{d}/{v}", exist_ok=True)
argv = [sys.executable, f"{ROOT}/editor/roll.py", f"{d}/{nn}.jsonl", "--turn", "1", "--n", n, "--max-turns", "3",
        "--stop", "end", "--out", f"{d}/{v}/{nn}.roll.jsonl"]
if v != "0":
    for old, new in json.load(open(f"{d}/{v}/{nn}.sub.json")):
        argv += ["--sub", old, new]
bench, view = VIEW[nn]
argv += ["--", "--home", f"{home}/h_{v}_{nn}", "--tag", f"s6{v}{nn}", "--bench", bench, "--view", f"{t}/{view}",
         "--input-text", f"{t}/in/{nn}_v_rr.txt", "--seed", "1", "--stand", "default", "--lint", f"{ROOT}/editor/lint",
         "--ticket", f"{ROOT}/docs/tickets_1106k/{nn}.json"]
os.execv(sys.executable, argv)
