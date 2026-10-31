"""Политики: переопределение имён любого модуля исследователя (POLICIES, --set KEY=JSON) и пересборка промпта.
Имя меняется в модуле-владельце (owner): там его читают функции, так что новое значение видно всем."""
import sys

from .. import facade as _facade
from . import cfg as C
from . import prompt as P
from . import views as V
from . import sandbox as S
from . import check as K
from . import notes as N
from . import trace as T
from . import evidence as E
from . import model as M
from . import session as L
from . import state as R
from . import context as CX
from . import tools as TO
from . import turn as TU
from . import phase as PH
from . import nudge as NG

PARTS = (C, P, V, S, K, N, T, E, M, L, R, CX, TO, TU, PH, NG, sys.modules[__name__])


def owner(k):
    """Модуль пакета, где определено имя k (импортированные модули не в счёт) -> модуль или None."""
    return _facade.owner(PARTS, k)


STAND_KEYS = {"URL", "MODEL", "TEMP", "THINKING", "THINK_BUDGET", "MAX_GEN", "STAND"}   # только из профиля стенда


def apply_policy(name, overrides=None):
    for k, v in {**C.POLICIES[name], **(overrides or {})}.items():
        m = owner(k)
        assert m is not None, k
        assert k not in STAND_KEYS, f"{k} comes from the stand profile (stands/*.json), not from a policy or --set"
        setattr(m, k, v)
    assert C.EVIDENCE_MODE in ("strict", "free"), C.EVIDENCE_MODE
    C.ALLOWED = set(C.ALLOWED_BASE) | ({"python3"} if C.PYTHON else set()) | ({"runs"} if C.RUNS_TOOL else set())
    C.POLICY = C.VARIANT = name
    P.REPORT_EXAMPLE = P.build_report_example()
    P.SYSTEM = P.build_system()
    P.TOOLS = P.build_tools()
    P.FINAL_TOOLS = [x for x in P.TOOLS if x["function"]["name"] in ("report", "finish")]


def apply_stand(name, roles=("agent",)):
    """Модель и параметры генерации — из профиля стенда; живой стенд сверяется с ним (иначе SystemExit)."""
    if C.ROOT not in sys.path:
        sys.path.insert(0, C.ROOT)                     # stand.py и stands/ — в корне репозитория
    import stand as ST
    prof = ST.load(name)
    rec = ST.check(prof, list(roles))
    g = ST.gen(prof, "agent")
    C.URL, C.MODEL, C.TEMP = g["url"] + "/chat/completions", g["model"], g["temperature"]
    C.MAX_GEN, C.THINKING, C.THINK_BUDGET = g["max_tokens"], g["thinking"], g["think_budget"]
    C.STAND = ST.meta(prof, rec)
    return C.STAND

