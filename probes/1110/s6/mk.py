"""Шаг 6 тикета 10.11: псевдологи из снимка базы — одна запись меты, чтобы editor/fork.py снял первый ход.
python3 probes/1110/s6/mk.py BASE_DIR OUT_DIR NN...   (модель не вызывается)
"""
import json
import sys

base, out, nns = sys.argv[1], sys.argv[2], sys.argv[3:]
system = open(f"{base}/system.txt").read()[:-1]  # snap.py дописал перевод строки
for nn in nns:
    meta = {"type": "meta", "system": system, "first_user": open(f"{base}/first.{nn}.txt").read()}
    open(f"{out}/{nn}.jsonl", "w").write(json.dumps(meta, ensure_ascii=False) + "\n")
    print(nn, len(meta["system"]), len(meta["first_user"]))
