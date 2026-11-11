"""11.11: виды runs/typed_1110 -> runs/typed_1111. Из app_r1 и app_r4 убрана проверка «The previous step produced this
output again»: она сравнивает код ответа с выводом прошлого шага и не срабатывает никогда (след старых узлов e3–e8).
Из app_r1 убрана и output_text — больше ей пользоваться некому; в app_r4 она остаётся, её зовёт _is_new_step (вход 04).
Остальные виды — копии; README всех видов — из nrhsi/plain.py (в нём назван конец эпизода
защитой моста, «repeated reply»). Во входах 01, 03, 04 сдвинуты ссылки на строки src/harness.py. Из app_r1 убран run 19, из входов — 02 (см. ниже). typed_1110 не меняется: на нём
записаны прежние сессии и идут проигрыши probes/1110/gold. Проверка — tests/rerun.py в копии писателя: «no changes».

  python3 tools/port_typed_1111.py"""
import shutil
import sys
from pathlib import Path

N = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(N / "nrhsi"))
import plain  # noqa: E402
OLD, NEW = N / "runs/typed_1110", N / "runs/typed_1111"

OUTPUT_TEXT = '''def output_text(content):
    blocks = all_python_blocks(content)
    if blocks:
        return blocks[0].strip()
    return content


'''
DEAD = '''        if steps and output_text(content) == steps[-1].output:
            messages.append(user("The previous step produced this output again. Stop repeating it. If you "
                                "have nothing else to try, call apis.supervisor.complete_task to finish "
                                "the task."))
%s            continue
'''
CUT = {"app_r1": [OUTPUT_TEXT, DEAD % ""],
       "app_r4": [DEAD % "            steps.append(Step(None, None))\n"]}
REFS = {"01": [("src/harness.py:102-106", "src/harness.py:95-99")],
        "03": [("src/harness.py:103-105", "src/harness.py:96-98"), ("(src/harness.py:102)", "(src/harness.py:95)")],
        "04": [("src/harness.py:139", "src/harness.py:133")]}


def cut(text, pairs, what):
    for old, new in pairs:
        assert text.count(old) == 1, (what, old[:50], text.count(old))
        text = text.replace(old, new)
    return text


NEW.mkdir(exist_ok=True)
(NEW / "in").mkdir(exist_ok=True)
for d in sorted(p for p in OLD.iterdir() if p.is_dir() and p.name != "in"):
    if (NEW / d.name).exists():
        shutil.rmtree(NEW / d.name)
    shutil.copytree(d, NEW / d.name, symlinks=True)
    (NEW / d.name / "README.md").write_text(plain.README[d.name[:3]])     # README: конец эпизода защитой моста назван
    if d.name in CUT:
        h = NEW / d.name / "src/harness.py"
        h.write_text(cut(h.read_text(), [(c, "") for c in CUT[d.name]], d.name))
# run 19 вида app_r1 записан 31.10 в 10:16, до защиты моста (71ec12f, 17:18): 394 одинаковых ответа подряд на нынешнем
# мосте невозможны, эпизод кончился бы на третьем. Прогон и вход 02, который описывает его, из набора убраны.
(NEW / "app_r1/logs/run_19.jsonl").unlink()
r = NEW / "app_r1/logs/results.jsonl"
lines = r.read_text().splitlines()
kept = [l for l in lines if '"run": 19,' not in l]
assert len(kept) == len(lines) - 1
r.write_text("\n".join(kept) + "\n")
(NEW / "in/02_v_rr.txt").unlink(missing_ok=True)
for f in sorted((OLD / "in").iterdir()):
    if f.name[:2] != "02":
        (NEW / "in" / f.name).write_text(cut(f.read_text(), REFS.get(f.name[:2], []), f.name))
print("ok")
