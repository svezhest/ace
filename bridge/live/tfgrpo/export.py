"""Выход апстрима из его БД (sqlite прогона) в JSON рядом с записью: experiences.json — опыты после последнего шага
(ExperienceCache), samples.json — rollout практики и ответы итогового агента в порядке БД (order_by dataset_index).
usage: python export.py OUT/test.db DIR"""
import json
import sqlite3
import sys

db, out = sqlite3.connect(sys.argv[1]), sys.argv[2]
experiences = db.execute("select experiences from cache_experience order by step desc limit 1").fetchone()[0]
json.dump(json.loads(experiences), open(f"{out}/experiences.json", "w"), ensure_ascii=False, indent=1)
fields = ("exp_id", "dataset_index", "raw_question", "correct_answer", "augmented_question", "response", "reward",
          "correct", "stage")
rows = db.execute(f"select {', '.join(fields)} from evaluation_data order by exp_id desc, dataset_index, id").fetchall()
json.dump([dict(zip(fields, r)) for r in rows], open(f"{out}/samples.json", "w"), ensure_ascii=False, indent=1)
