"""БД апстрима для записи (sqlite, UTU_DB_URL): DAPO-Math-17k и AIME24 — load_data из
scripts/data/process_training_free_GRPO_data.py как есть (parquet DAPO скачан заранее в DIR/data/DAPO-Math-17k/data,
snapshot_download — no-op); срезы через scripts/data/upload_dataset.py апстрима:
DAPO-Math-17k-live — первые 16 вопросов DAPO в порядке апстрима на английском с условием короче 160 символов
(как data/dapo_train40.jsonl стенда; четыре батча по 4), AIME24-live — первые 4 задачи AIME24 (итоговый тест).
usage (venv youtu, UTU_* и UTU_DB_URL=sqlite:///DB): python prep.py DIR"""
import importlib.util
import json
import os
import pathlib
import re
import sqlite3
import sys

REPO = pathlib.Path(os.environ.get("UPSTREAMS", "~/Projects/upstreams")).expanduser() / "youtu-agent"
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
rows = db.execute("select question, answer, source from data where dataset = ? order by \"index\"", ("DAPO-Math-17k",))
cjk = re.compile(r"[　-鿿＀-￯]")
upload([r for r in rows if len(r[0]) < 160 and not cjk.search(r[0])][:16], "DAPO-Math-17k-live")
rows = db.execute("select question, answer, source from data where dataset = ? order by \"index\"", ("AIME24",))
upload(list(rows)[:4], "AIME24-live")
