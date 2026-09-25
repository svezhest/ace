"""MCE против записи апстрима meta-context-engineering c4b7a7c на живой модели (bridge/live/mce, run.json):
symptom_diagnosis, 1 итерация (вторая не влезла в бюджет модели), train 2 одним батчем, val 2, затем тест лучшей
итерации на 2 вопросах test.
Запись воспроизводится без модели (tools/record/replay) под mce стенда: мета-агент и базовый агент — тот же
Claude Agent SDK (CLI из пакета) через LiteLLM proxy, workspace — тот же ROOT на диске, окружение CLI — как у
записи. Каждый запрос — вывода задачи, обоих агентов и фоновых вызовов CLI — совпадает с записанным (сравнение без
вывода команд Bash хоста и даты в описании WebSearch: DEVIATIONS MCE7), все записанные ответы востребованы;
workspace на выходе (навыки, context/, interfaces/, train.json, evaluations.json по итерациям) — как у апстрима,
лучшая итерация и ответы теста — как у его mce.eval."""
import json
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path

import pytest

from ace import config
from ace.learner import swap
from ace.loop import run
from ace.memory.mce import folder_name
from ace.methods.mce import mce
from ace.model import Model, claude
from ace.tasks import TASKS
from tools.record.mce import normalize
from tools.record.replay import Replayer

LIVE = Path(__file__).resolve().parents[2] / "bridge" / "live" / "mce"
RUN = json.load(open(LIVE / "run.json")) if (LIVE / "run.json").exists() else {"root": "/private/tmp/mce-live"}
ROOT = Path(RUN["root"])
LITELLM = config.UPSTREAMS / ".venvs" / "litellm" / "bin" / "litellm"

pytestmark = pytest.mark.skipif(not (LIVE / "rec.jsonl").exists() or not LITELLM.exists() or not config.MCE_VENV.exists(),
                                reason="нет записи bridge/live/mce/rec.jsonl, venv LiteLLM или venv апстрима MCE")


def strays():
    """Файлы вне ROOT, которые агенты записи создают инструментом Write (скрипты анализа в /tmp): до
    воспроизведения их не должно быть, иначе Write CLI ответит иначе (файл не прочитан)."""
    out = set()
    for line in open(LIVE / "rec.jsonl"):
        for choice in json.loads(line)["response"].get("choices") or []:
            for call in choice["message"].get("tool_calls") or []:
                if call["function"]["name"] == "Write":
                    path = json.loads(call["function"]["arguments"]).get("file_path", "")
                    if path.startswith("/") and not Path(path).resolve().is_relative_to(ROOT):
                        out.add(Path(path))
    return out


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def litellm(model_url, tmp):
    """LiteLLM proxy с конфигом записи (bridge/live/mce/litellm.yaml), направленный на воспроизведение."""
    port = free_port()
    cfg = tmp / "litellm.yaml"
    cfg.write_text((LIVE / "litellm.yaml").read_text().replace("http://127.0.0.1:8090/v1", model_url))
    proc = subprocess.Popen([str(LITELLM), "--config", str(cfg), "--port", str(port), "--host", "127.0.0.1"],
                            env={"HOME": str(tmp), "PATH": "/usr/bin:/bin"}, stdout=open(tmp / "litellm.log", "w"),
                            stderr=subprocess.STDOUT)
    for _ in range(600):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=1).close()
            return proc, f"http://127.0.0.1:{port}"
        except OSError:
            time.sleep(0.1)
    proc.kill()
    raise RuntimeError("LiteLLM не поднялся")


@pytest.fixture(scope="module")
def replayed(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("mce")
    if ROOT.exists():
        shutil.rmtree(ROOT)
    for path in strays():
        path.unlink(missing_ok=True)
    srv = Replayer(("127.0.0.1", 0), LIVE / "rec.jsonl", normalize)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/v1"
    proc, proxy = litellm(url, tmp)
    patch = pytest.MonkeyPatch()
    try:
        patch.setattr(config, "CLAUDE_BASE_URL", proxy)
        patch.setattr(config, "VAL_SIZE", RUN["val_limit"])
        patch.setattr(config, "SEED", RUN["seed"])
        ROOT.mkdir(parents=True)
        patch.chdir(ROOT)               # cwd процесса апстрима — корень (относительные пути в коде интерфейсов)
        learner = swap(mce, every=RUN["train_batch_size"])
        learner.root, learner.workspace = ROOT, RUN["workspace"]
        model = Model(RUN["model"], url, backend="wire")
        run(TASKS["symptom"], learner, model, RUN["train_limit"], str(tmp / "out"), epochs=RUN["iterations"],
            offline=True)
    finally:
        patch.undo()
        proc.kill()
        srv.shutdown()
    return srv.status(), json.load(open(tmp / "out" / "log.json"))


def files(base):
    """Файлы workspace без utils/ (копия mce/workspace_utils) и __pycache__."""
    return {str(p.relative_to(base)): p.read_bytes() for p in sorted(base.rglob("*"))
            if p.is_file() and "utils" not in p.relative_to(base).parts and "__pycache__" not in p.parts}


def test_requests(replayed):
    status, _ = replayed
    assert status["misses"] == 0 and status["unused"] == 0 and status["served"] == status["recorded"]


def test_workspace(replayed):
    """Навыки, context/, interfaces/, data/train.json каждой итерации, evaluations.json и архив навыков."""
    ours, theirs = files(ROOT / "workspace" / RUN["workspace"]), files(LIVE / "workspace")
    assert sorted(ours) == sorted(theirs)
    assert [p for p in ours if ours[p] != theirs[p]] == []


def test_best_and_test(replayed):
    """Лучшая по val итерация и ответы теста ею — как у mce.eval апстрима на её последней папке."""
    _, log = replayed
    evals = json.loads((LIVE / "workspace" / "meta_agent" / "evaluations.json").read_text())
    best = max(evals, key=lambda k: evals[k]["val_accuracy"])
    assert best == RUN["best"]
    theirs = json.load(open(LIVE / "test_evaluation.json"))["results"]
    test = [r for r in log if r["phase"] == "test"]
    assert [r["correct"] for r in test] == [r["evaluation"]["metrics"]["accuracy"] == 1.0 for r in theirs]
    assert [r["answer"] for r in test] == [r["evaluation"]["trajectory"][-1]["prediction"] for r in theirs]


def test_env():
    """Окружение CLI стенда — то же, что у записи (bridge/live/mce/env.txt), с адресами прокси и модели."""
    ours = claude.env(ROOT, "http://127.0.0.1:8090/v1")
    ours["ANTHROPIC_BASE_URL"] = "http://127.0.0.1:4000"
    theirs = dict(line.split("=", 1) for line in (LIVE / "env.txt").read_text().replace("@ROOT@", str(ROOT)).splitlines())
    assert ours == theirs


def test_folders():
    assert folder_name(1, 0) == "iter1_sub0" and folder_name(0) == "iter0"
