"""Воспроизведение записей живой модели (bridge/live) без модели."""
import json
import threading
from contextlib import contextmanager
from pathlib import Path

from ace.model import Model
from tools.record.replay import Replayer

MODEL = "ornith15-9b"       # модель, на которой сняты записи bridge/live
LIVE = Path(__file__).resolve().parents[2] / "bridge" / "live"


@contextmanager
def replay(rec, port=0, normalize=None):
    """Сервер воспроизведения записи rec на своём потоке; после блока останавливается (status() — и после)."""
    srv = Replayer(("127.0.0.1", port), rec, normalize)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield srv
    finally:
        srv.shutdown()


def replaying(srv):
    """Модель стенда на проводе к воспроизведению srv (tools/record/replay)."""
    return Model(MODEL, f"http://127.0.0.1:{srv.server_address[1]}/v1", backend="wire")


class Mixed(Model):
    """Модель, какой снята запись scope_code (bridge/live/scope/driver.py на проводе, пока вызовы с инструментами на
    нём молча уходили в pydantic-ai): решатель с инструментами — pydantic-ai, остальное — провод. Только чтобы
    воспроизвести ту запись; в стенде бэкенд один на все вызовы."""
    def ask(self, call):
        return self.agent.ask(call) if call.tools else self.wire.ask(call)


def mixed(srv):
    return Mixed(MODEL, f"http://127.0.0.1:{srv.server_address[1]}/v1", backend="wire")


def requests(rec):
    """Тела записанных запросов по порядку записи."""
    return [json.loads(json.loads(line)["request"]) for line in open(rec)]
