"""БД апстрима для записи (sqlite, UTU_DB_URL): DAPO-Math-17k и AIME24 — load_data из
scripts/data/process_training_free_GRPO_data.py как есть (parquet DAPO скачан заранее в DIR/data/DAPO-Math-17k/data,
snapshot_download — no-op). Обучение берёт DAPO-Math-17k целиком, срез — ручкой апстрима --rollout_data_truncate.
Итоговый тест — AIME24-live, первые 4 задачи AIME24 через scripts/data/upload_dataset.py апстрима (README, Option 2):
у run_eval.py ручки среза нет.
usage (venv youtu, UTU_* и UTU_DB_URL=sqlite:///DB): python prep.py DIR"""
import importlib.util
import json
import os
import pathlib
import sqlite3
import sys

UP = os.environ.get("UPSTREAMS") or pathlib.Path(__file__).resolve().parents[2] / "upstreams"
REPO = pathlib.Path(UP) / "youtu-agent"
sys.path.insert(0, str(REPO))


def script(name):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / "data" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def upload(rows, name):
    path = data / f"{name}.jsonl"
    with open(path, "w") as f:
        for q, a, s in rows:
            f.write(json.dumps({"question": q, "answer": a, "source": s}, ensure_ascii=False) + "\n")
    script("upload_dataset").upload_dataset(str(path), name, data_format="default")


data = pathlib.Path(sys.argv[1])
prep = script("process_training_free_GRPO_data")
prep.DIR_ROOT = data
prep.snapshot_download = lambda **kw: None
for name in ("DAPO-Math-17k", "AIME24"):
    print(name, len(prep.load_data(name)))

from utu.utils import EnvUtils  # noqa: E402

db = sqlite3.connect(EnvUtils.get_env("UTU_DB_URL").removeprefix("sqlite:///"))
# исключение (автор, 29.09): задача DAPO №7 (S={1..98}, 10 чисел и взаимная простота) — модель пишет на ней
# переборы, поток python_executor по таймауту не умирает (issue #256), rollout раз за разом упирается в 3600 с;
# 10 ч прогона ушли на неё. Срез --rollout_data_truncate 16 берёт вместо неё следующую, №16
q = db.execute("select question from data where dataset = 'DAPO-Math-17k' and \"index\" = 7").fetchone()[0]
assert q.startswith("设 S=\\{1,2,\\cdots,98\\}"), q[:40]
db.execute("delete from data where dataset = 'DAPO-Math-17k' and \"index\" = 7")
db.commit()
rows = db.execute("select question, answer, source from data where dataset = ? order by \"index\"", ("AIME24",))
upload(list(rows)[:4], "AIME24-live")
