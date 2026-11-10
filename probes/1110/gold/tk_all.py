"""ticket_check на готовых рабочих копиях (итог сессий G7–G9, F2): python3 tk_all.py OUT.txt ROOT..."""
import sys, types
from concurrent.futures import ProcessPoolExecutor
sys.path.insert(0, "/Users/user/Projects/nrhsi")
from nrhsi.editor import cfg as C, gate as G

def one(root):
    C.BENCH = "alf"; C.VIEWS = {"alf": "/Users/user/Projects/nrhsi/runs/typed_1110/alf_r1"}
    C.TICKET = {"change_expected": "control", "runs": [40], "keep": [28]}
    C.TICKET_LINE = C.TICKET_VALUES = C.TICKET_WHY = True
    C.HERE = "/tmp/claude-501/tk_all"
    run = types.SimpleNamespace(root=root, last_rerun="", w=lambda rec: None)
    try:
        return root, G.ticket_check(run)
    except Exception as e:
        return root, f"EXC {type(e).__name__}: {e}"

if __name__ == "__main__":
    import os
    os.makedirs("/tmp/claude-501/tk_all", exist_ok=True)
    with ProcessPoolExecutor(6) as ex, open(sys.argv[1], "w") as f:
        for root, t in ex.map(one, sorted(sys.argv[2:])):
            f.write(f"== {'/'.join(root.split('/')[-3:])}\n{t}\n")
