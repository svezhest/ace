"""MCE против записи апстрима meta-context-engineering c4b7a7c на живой модели (bridge/live/mce, run.json):
symptom_diagnosis, 1 итерация, train 2 одним батчем, val 2. Запись обрывается в сессии базового агента (run.json:
cutoff) — сверяется всё до обрыва. Запись воспроизводится без модели (tools/record/replay) под mce стенда:
мета-агент и базовый агент — тот же Claude Agent SDK (CLI из пакета) через LiteLLM proxy, workspace — тот же ROOT
на диске, окружение CLI — как у записи, адрес модели — тот же. Каждый записанный запрос — вывода задачи, обоих
агентов и фоновых вызовов CLI — совпадает с пришедшим (без вывода команд Bash хоста и даты в описании WebSearch:
DEVIATIONS MCE7) и востребован ровно раз, первый незаписанный запрос приходит только после всех записанных;
workspace в точке обрыва (SKILL.md, context/, data/train.json, meta_agent/) — как у апстрима."""
import gzip
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
RUN = json.load(open(LIVE / "run.json"))
ROOT = Path(RUN["root"])
LITELLM = config.UPSTREAMS / ".venvs" / "litellm" / "bin" / "litellm"

pytestmark = pytest.mark.skipif(not (LIVE / "rec.jsonl.gz").exists() or not LITELLM.exists() or not config.MCE_VENV.exists(),
                                reason="нет записи bridge/live/mce/rec.jsonl, venv LiteLLM или venv апстрима MCE")


def strays():
    """Файлы вне ROOT, которые агенты записи создают инструментом Write (скрипты анализа в /tmp): до
    воспроизведения их не должно быть, иначе Write CLI ответит иначе (файл не прочитан)."""
    out = set()
    for line in gzip.decompress((LIVE / "rec.jsonl.gz").read_bytes()).decode().splitlines():
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


class Cut(Replayer):
    """Воспроизведение, которое помнит, сколько ответов было отдано к первому промаху."""
    first_miss = None

    def miss(self, path, c, n):
        if self.first_miss is None:
            self.first_miss = sum(self.used.values())
        return super().miss(path, c, n)


@pytest.fixture(scope="module")
def replayed(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("mce")
    if ROOT.exists():
        shutil.rmtree(ROOT)
    for path in strays():
        path.unlink(missing_ok=True)
    rec = tmp / "rec.jsonl"
    rec.write_bytes(gzip.decompress((LIVE / "rec.jsonl.gz").read_bytes()))
    # тот же адрес, что у записи: агенты видят его в окружении и зовут модель сами (utils/llm.py, urllib)
    srv = Cut(("127.0.0.1", RUN["model_port"]), rec, normalize)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{RUN['model_port']}/v1"
    proc, proxy = litellm(url, tmp)
    patch = pytest.MonkeyPatch()
    error = None
    try:
        patch.setattr(config, "CLAUDE_BASE_URL", proxy)
        patch.setattr(config, "VAL_SIZE", RUN["val_limit"])
        patch.setattr(config, "SEED", RUN["seed"])
        ROOT.mkdir(parents=True)
        patch.chdir(ROOT)               # cwd процесса апстрима — корень (относительные пути в коде интерфейсов)
        learner = swap(mce, every=RUN["train_batch_size"])
        learner.root, learner.workspace = ROOT, RUN["workspace"]
        model = Model(RUN["model"], url, backend="wire")
        try:
            run(TASKS["symptom"], learner, model, RUN["train_limit"], str(tmp / "out"), epochs=RUN["iterations"],
                offline=True)
        except RuntimeError as e:       # запись кончилась в сессии базового агента: проверка интерфейсов не прошла
            error = str(e)
    finally:
        patch.undo()
        proc.kill()
        srv.shutdown()
    return srv, error


def files(base):
    """Файлы workspace без utils/ (копия mce/workspace_utils) и __pycache__."""
    return {str(p.relative_to(base)): p.read_bytes() for p in sorted(base.rglob("*"))
            if p.is_file() and "utils" not in p.relative_to(base).parts and "__pycache__" not in p.parts}


def test_requests(replayed):
    srv, error = replayed
    status = srv.status()
    assert status["served"] == status["recorded"] == RUN["calls"] and status["unused"] == 0
    assert srv.first_miss == status["recorded"]         # незаписанное — только после обрыва записи
    assert error and "Base-agent failed at iter1_sub0" in error


def test_workspace(replayed):
    """SKILL.md мета-агента, context/ базового агента, data/train.json батча и meta_agent/ в точке обрыва."""
    ours, theirs = files(ROOT / "workspace" / RUN["workspace"]), files(LIVE / "workspace")
    assert sorted(ours) == sorted(theirs)
    assert [p for p in ours if ours[p] != theirs[p]] == []


def test_env():
    """Окружение CLI стенда — то же, что у записи (bridge/live/mce/env.txt), с адресами прокси и модели."""
    ours = claude.env(ROOT, "http://127.0.0.1:8090/v1")
    ours["ANTHROPIC_BASE_URL"] = "http://127.0.0.1:4000"
    theirs = dict(line.split("=", 1) for line in (LIVE / "env.txt").read_text().replace("@ROOT@", str(ROOT)).splitlines())
    assert ours == theirs


def test_folders():
    assert folder_name(1, 0) == "iter1_sub0" and folder_name(0) == "iter0"
