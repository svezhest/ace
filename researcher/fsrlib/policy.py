"""Политики: переопределение имён любого модуля fsrlib (POLICIES, --set KEY=JSON) и пересборка промпта.
Имя меняется в модуле-владельце (owner): там его читают функции, так что новое значение видно всем."""
import sys
import types

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

PARTS = (C, P, V, S, K, N, T, E, M, L, sys.modules[__name__])
_NO = object()


def owner(k):
    """Модуль fsrlib, где определено имя k (импортированные модули не в счёт) -> модуль или None."""
    if k.startswith("__"):
        return None
    for m in PARTS:
        v = vars(m).get(k, _NO)
        if v is not _NO and not isinstance(v, types.ModuleType):
            return m
    return None


def apply_policy(name, overrides=None):
    for k, v in {**C.POLICIES[name], **(overrides or {})}.items():
        m = owner(k)
        assert m is not None, k
        setattr(m, k, v)
    assert C.EVIDENCE_MODE in ("strict", "free"), C.EVIDENCE_MODE
    C.ALLOWED = set(C.ALLOWED_BASE) | ({"python3"} if C.PYTHON else set()) | ({"runs"} if C.RUNS_TOOL else set())
    C.POLICY = C.VARIANT = name
    P.REPORT_EXAMPLE = P.build_report_example()
    P.SYSTEM = P.build_system()
    P.TOOLS = P.build_tools()
    P.FINAL_TOOLS = [x for x in P.TOOLS if x["function"]["name"] in ("report", "finish")]
