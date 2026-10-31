"""Стартовый src/ бенчмарка: общий шаблон start/template/ + патч start/<bench>.patch + файлы бенча start/<bench>/.

  python3 tools/make_start.py alfworld --out /tmp/src

Шаблон — общий цикл агента (harness.py) и пустые хуки (hooks.py); патч — только то, что навязывает бенч
(начало разговора, вызов модели, разбор ответа, ход в бенч и что приходит обратно); файлы бенча (промпты,
bridge.py) кладутся как есть. Результат должен совпадать с <bench>/view_v3/src байт в байт (тесты бенчей)."""
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("bench", choices=["alfworld", "appworld"])
    ap.add_argument("--out", default=None, help="по умолчанию start/build/<bench>/src")
    a = ap.parse_args()
    print(make(a.bench, a.out or START / "build" / a.bench / "src"))


if __name__ == "__main__":
    main()
