"""Запись EvoLib: eval_main.main() апстрима как есть на HMMT, клиенты и данные подменены здесь, в раннере.

    /Users/user/Projects/upstreams/.venvs/light/bin/python run.py OUT URL [ЗАДАЧ]
    (URL — записывающий прокси tools/record с --seed и --embeddings-upstream на tools/record/embeddings.py;
    по готовой записи — tools/record/replay: прогон без модели, те же запросы и снимки)

Подмены (код апстрима не тронут):
    build_clients   Azure -> OpenAI(base_url=URL): LLMAgent и EmbeddingModel апстрима с его параметрами модели
                    задачи (HMMT: reasoning API, max_completion_tokens 50000, reasoning_effort high)
    azure           заглушка модуля: build_clients подменён, при импорте eval_main он всё равно нужен
    load_dataset    первые ЗАДАЧ (3) задач hmmt_feb_2025, остальные наборы пусты: i = kiter % data_size, задачи
                    повторяются, и на повторе работает сравнение решений
    matharena       чекер — extract_and_grade matharena (e927660, последний коммит до коммита EvoLib) с конфигом
                    соревнования hmmt_feb_2025.yaml; EvoLib зовёт его как (решение, ответ), у matharena вызов —
                    (сообщения, число токенов, ответ, конфиг): решение — одно сообщение assistant; axle (Lean) —
                    заглушка, для HMMT не нужен
    random.seed     сида у апстрима нет: ставится перед циклом итераций (setup_state)
Снимок после каждой итерации (log_iteration): библиотеки skills и insights без эмбеддингов и лучшие решения задач —
OUT/steps.json."""
import json
import os
import random
import sys
import types

UP = os.environ.get("UPSTREAMS", "/Users/user/Projects/upstreams")
SRC = f"{UP}/EvoLib/EvoLib"
SEED = 0
OUT, URL = sys.argv[1], sys.argv[2]
TASKS = int(sys.argv[3]) if len(sys.argv) > 3 else 3
ITERATIONS, K = 5, 3

sys.path[:0] = [SRC, f"{UP}/matharena/src"]
for name in ("azure", "azure.identity"):
    sys.modules[name] = types.ModuleType(name)
for attr in ("AzureCliCredential", "ChainedTokenCredential", "ManagedIdentityCredential", "get_bearer_token_provider"):
    setattr(sys.modules["azure.identity"], attr, None)
axle = sys.modules["axle"] = types.ModuleType("axle")
axle.AxleClient = axle.CheckResponse = None

import datasets  # noqa: E402
import yaml  # noqa: E402
from matharena import grader  # noqa: E402
from openai import OpenAI  # noqa: E402

import eval_main  # noqa: E402
from embed import EmbeddingModel  # noqa: E402
from evolib_agent import EvoLibAgent  # noqa: E402
from llm import LLMAgent  # noqa: E402

HMMT = yaml.safe_load(open(f"{UP}/matharena/configs/competitions/hmmt/hmmt_feb_2025.yaml"))
grade = grader.extract_and_grade


def extract_and_grade(solution, gold):
    return grade([{"role": "assistant", "content": solution}], 0, gold, HMMT)


grader.extract_and_grade = extract_and_grade

load = datasets.load_dataset


def load_dataset(name, split):
    d = load(name, split=split)
    return d.select(range(TASKS) if name == "MathArena/hmmt_feb_2025" else [])


datasets.load_dataset = load_dataset


def build_clients(args, default_model, use_reasoning, reasoning_effort):
    client = OpenAI(base_url=URL, api_key="x")
    llm = LLMAgent(client=client, model=args.model or default_model, use_reasoning_api=use_reasoning,
                   reasoning_effort=reasoning_effort)
    return llm, EmbeddingModel(client=client)


eval_main.build_clients = build_clients

setup = EvoLibAgent.setup_state


def setup_state(self):
    random.seed(SEED)
    setup(self)


EvoLibAgent.setup_state = setup_state

steps, best = [], {}
log = eval_main.log_iteration


def log_iteration(log_file, agent, llm, kiter, problem_idx, info, result, mean_score):
    if result["is_improving"]:
        best[problem_idx] = [result["best_score"], result["best_solution"]]
    # копия сразу: журналы Future IG — общие списки, апстрим дописывает их на следующих итерациях
    steps.append(json.loads(json.dumps({"iteration": kiter, "problem": problem_idx, "result": result,
                                        "skills": [[s, v[0], v[1], v[2]] for s, v in agent.skill_lib.items()],
                                        "insights": [[s, v[0]] for s, v in agent.insight_lib.items()],
                                        "best": {str(i): b for i, b in sorted(best.items())}})))
    json.dump(steps, open(f"{OUT}/steps.json", "w"), ensure_ascii=False, indent=1)
    log(log_file, agent, llm, kiter, problem_idx, info, result, mean_score)


eval_main.log_iteration = log_iteration

sys.argv = ["eval_main.py", "--task", "hmmt", "--model", "ornith15-9b", "--k_q_per_problem", str(K),
            "--n_iterations", str(ITERATIONS), "--log_file", f"{OUT}/evolib.log"]
eval_main.main()
