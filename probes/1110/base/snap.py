"""Снимок базы писателя: всё, что модель получает до первого хода, файлами.
python3 probes/1110/base/snap.py OUT   (из корня репозитория; модель не вызывается)
Пишет: system.txt (один для обоих бенчей), first.NN.txt (первое сообщение входа NN с тикетом), first.NN.noticket.txt для 00 и 08,
README.<bench>.md и tree.<bench>.txt (README и состав копии писателя без logs/; у видов одного бенча совпадают), tools.json (описания инструментов), MANIFEST (sha256 каждого файла).
"""
import hashlib
import json
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
from nrhsi.editor import cfg as C, prompt as P, inputs as IN, work as WK, schema as SC  # noqa: E402

T = f"{ROOT}/runs/typed_1110"
INPUTS = {"00": ("alf", "alf_n4"), "01": ("app", "app_r1"), "02": ("app", "app_r1"), "03": ("app", "app_r1"),
          "04": ("app", "app_r4"), "05": ("app", "app_r4"), "06": ("alf", "alf_r1"), "07": ("alf", "alf_r4chk"),
          "08": ("alf", "alf_r1"), "09": ("app", "app_n2")}


def main(out):
    os.makedirs(out, exist_ok=True)
    files = {}
    C.LINT = f"{ROOT}/editor/lint"
    files["system.txt"] = P.system() + "\n"
    for nn, (bench, view) in INPUTS.items():
        C.VIEWS[bench] = f"{T}/{view}"
        C.TICKET = json.load(open(f"{ROOT}/docs/tickets_1106k/{nn}.json"))
        files[f"first.{nn}.txt"] = IN.first_user(text_path=f"{T}/in/{nn}_v_rr.txt")
        if nn in ("00", "08"):
            C.TICKET = None
            files[f"first.{nn}.noticket.txt"] = IN.first_user(text_path=f"{T}/in/{nn}_v_rr.txt")
        C.HERE = tempfile.mkdtemp()
        root = WK.build_work(bench, "t")
        readme = open(f"{root}/README.md").read()
        tree = "\n".join(sorted(os.path.relpath(os.path.join(d, f), root) for d, _, fs in os.walk(root) for f in fs
                                if "/logs" not in d[len(root):] and "__pycache__" not in d)) + "\n"
        shutil.rmtree(C.HERE)
        # README и состав копии у всех видов одного бенча совпадают — проверяется здесь
        assert files.setdefault(f"README.{bench}.md", readme) == readme and files.setdefault(f"tree.{bench}.txt", tree) == tree
    files["tools.json"] = json.dumps(SC.TOOLS, ensure_ascii=False, indent=1) + "\n"
    man = []
    for name, text in sorted(files.items()):
        open(f"{out}/{name}", "w").write(text)
        man.append(f"{hashlib.sha256(text.encode()).hexdigest()[:16]}  {len(text):6d}  {name}")
    open(f"{out}/MANIFEST", "w").write("\n".join(man) + "\n")
    print("\n".join(man))


main(sys.argv[1])
