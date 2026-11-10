import subprocess, sys
from concurrent.futures import ThreadPoolExecutor
G = sys.argv[1]
def one(line):
    n, log, a = line.rstrip("\n").split("|")
    with open(f"{G}/cur/{n}.out", "w") as f:
        r = subprocess.run([sys.executable, "editor/replay.py", log, "--"] + a.split() + ["--home", f"{G}/cur/{n}", "--tag", "t"],
                           stdout=f, stderr=subprocess.STDOUT, cwd="/Users/user/Projects/nrhsi")
    return n, r.returncode
with ThreadPoolExecutor(6) as ex:
    for n, rc in ex.map(one, open(f"{G}/cur/jobs")):
        if rc:
            print("FAIL", n)
