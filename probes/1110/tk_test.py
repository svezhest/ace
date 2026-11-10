"""Проверка тикета на готовой рабочей копии: python3 tk_test.py ROOT [ROOT...]  (ROOT — копия с src/ и logs/)."""
import sys, types
sys.path.insert(0, "/Users/user/Projects/nrhsi")
from nrhsi.editor import cfg as C, gate as G
C.BENCH = "alf"; C.VIEWS = {"alf": "/Users/user/Projects/nrhsi/runs/typed_1110/alf_r1"}
C.TICKET = {"change_expected": "control", "runs": [40], "keep": [28]}
C.TICKET_LINE = C.TICKET_VALUES = C.TICKET_WHY = True
C.HERE = sys.argv[1].rsplit("/work/", 1)[0]
for root in sys.argv[1:]:
    run = types.SimpleNamespace(root=root, last_rerun="")
    changed = G._changed_lines(run)
    watch = G._watch(changed); watch["__shape__"] = True
    print("==", root.split("/")[-1])
    for k, v in watch.items():
        if k != "__shape__":
            print("  watch", k); [print("      ", e) for e in v]
    div, cov = G._replay(f"{root}/src", root, [40], cover=True, watch=watch)
    print("  div:", div.get("40"))
    print("  FACT:", G._dead_fact(changed, cov.get("40") or {}, frozenset(), 40))
