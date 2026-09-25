"""Воспроизведение записей живой модели (bridge/live) без модели."""
from ace.model import Model

MODEL = "ornith15-9b"       # модель, на которой сняты записи bridge/live


def replaying(srv):
    """Модель стенда на проводе к воспроизведению srv (tools/record/replay)."""
    return Model(MODEL, f"http://127.0.0.1:{srv.server_address[1]}/v1", backend="wire")
