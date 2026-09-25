"""Запись MCE на живой модели: mce.main апстрима как есть (meta-context-engineering c4b7a7c) на symptom_diagnosis,
1 итерация, train 2 одним батчем, val 2; затем тест лучшей по val итерации (mce.eval апстрима) на первых 2 test.
Параллелизм 1 (MAX_CONCURRENCY зашит в eval.py) и сид выборки train (random без сида у апстрима) — здесь, код не
меняется. Запускается из копии апстрима (run.sh), окружение — только то, что задаёт run.sh."""
import asyncio
import json
import random
import sys
from pathlib import Path

import mce.eval
from mce.main import main

mce.eval.MAX_CONCURRENCY = 1
ARGS = ["--workspace", "workspace/live", "--env", "symptom_diagnosis",
        "--train-data", "env/symptom_diagnosis/data/train.jsonl", "--val-data", "env/symptom_diagnosis/data/val.jsonl",
        "--model", "ornith15-9b", "--iterations", "1", "--train-limit", "2", "--train-batch-size", "2",
        "--val-limit", "2", "--log-dir", "logs"]
TEST = 2

random.seed(0)
sys.argv = ["mce.main", *ARGS]
asyncio.run(main())

# лучшая по val итерация (как max в main: строго больше, при равенстве первая) — тест её папкой
evals = json.load(open("workspace/live/meta_agent/evaluations.json"))
best = max(evals, key=lambda k: evals[k]["val_accuracy"])
print("best", best, flush=True)
sys.argv = ["mce.eval", "--iter_dir", f"workspace/live/{evals[best]['last_sub_folder']}", "--env", "symptom_diagnosis",
            "--data", "env/symptom_diagnosis/data/test.jsonl", "--limit", str(TEST), "--model", "ornith15-9b",
            "--save-results-to", "test"]
asyncio.run(mce.eval.main())
Path("best.txt").write_text(best)
