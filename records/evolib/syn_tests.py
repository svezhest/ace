"""Файл --syn_test_data_file: свои синтетические тесты апстрим не выложил (README: <livecodebench_synthetic_tests.json>).
Берутся публичные тесты задачи — примеры из условия, которые модель и так видит, — в формате get_evaluation_sample
lcb_runner и в порядке данных eval_main._build_livecode_task (v6, только hard).
    python syn_tests.py OUT.json   (cwd — корень LiveCodeBench)"""
import json
import sys

from lcb_runner.benchmarks import load_code_generation_dataset
from lcb_runner.benchmarks.code_generation import Difficulty

data = [x for x in load_code_generation_dataset(release_version="v6") if x.difficulty == Difficulty.HARD]
tests = [{"input_output": json.dumps({"inputs": [t.input for t in x.public_test_cases],
                                      "outputs": [t.output for t in x.public_test_cases],
                                      "fn_name": x.metadata.get("func_name", None)})} for x in data]
with open(sys.argv[1], "w") as f:
    json.dump(tests, f)
