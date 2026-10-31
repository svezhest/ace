"""Стартовый src/ бенчмарка: общий шаблон start/template/ + патч start/<bench>.patch + файлы бенча start/<bench>/.

  python3 tools/make_start.py alfworld --out /tmp/src

Шаблон — общий цикл агента (harness.py) и пустые хуки (hooks.py); патч — только то, что навязывает бенч
(начало разговора, вызов модели, разбор ответа, ход в бенч и что приходит обратно); файлы бенча (промпты,
bridge.py) кладутся как есть. Результат должен совпадать с <bench>/view_v3/src байт в байт, start/<bench>.README.md —
с <bench>/view_v3/README.md (тесты бенчей).

  python3 tools/make_start.py alfworld --view /tmp/n0     # вид узла: README.md + src/ (nrhsi/tree.py)"""
import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
START = ROOT / "start"


def make(bench, out):
    out = Path(out)
    if out.exists() and any(out.iterdir()):
        sys.exit(f"{out} is not empty")
    out.mkdir(parents=True, exist_ok=True)
    for f in sorted((START / "template").iterdir()):
        shutil.copy(f, out / f.name)
    subprocess.run(["patch", "-s", "-p1", "-d", str(out), "-i", str(START / f"{bench}.patch")], check=True)
    for f in sorted((START / bench).iterdir()):
        shutil.copy(f, out / f.name)
    left = [f.name for f in out.iterdir() if f.suffix in (".orig", ".rej")]
    assert not left, left
    return out


def make_view(bench, view):
    """Вид узла: <view>/README.md (start/<bench>.README.md — README для модели) + <view>/src (make)."""
    view = Path(view)
    make(bench, view / "src")
    shutil.copy(START / f"{bench}.README.md", view / "README.md")
    return view


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("bench", choices=["alfworld", "appworld"])
    ap.add_argument("--out", default=None, help="по умолчанию start/build/<bench>/src")
    ap.add_argument("--view", default=None, help="вместо --out: вид узла VIEW/README.md + VIEW/src")
    a = ap.parse_args()
    print(make_view(a.bench, a.view) if a.view else make(a.bench, a.out or START / "build" / a.bench / "src"))


if __name__ == "__main__":
    main()
