"""Опись постановки: фразы базы -> коммит, где фраза появилась в нынешнем виде, и цитирует ли её модель.
python3 probes/1110/inventory/origin.py BASE_DIR LOGS_GLOB... > таблица.tsv
Фразы: предложения system.txt, абзацы README.<bench>.md, описания инструментов. Происхождение — `git log -S` по
первым 60 знакам фразы (самый ранний коммит). Цитирование — сколько сессий, где в тексте или рассуждении модели
есть любые 5 слов фразы подряд (без учёта регистра).
"""
import glob
import json
import re
import subprocess
import sys

base, globs = sys.argv[1], sys.argv[2:]


def phrases():
    s = open(f"{base}/system.txt").read()
    for para in s.split("\n"):
        for ph in re.split(r"(?<=[.:;]) (?=[A-Z])", para.strip()):
            if len(ph) > 25:
                yield "system", ph.lstrip("- ")
    for t in json.load(open(f"{base}/tools.json")):
        yield "tool:" + t["function"]["name"], t["function"]["description"]
        for k, v in t["function"]["parameters"].get("properties", {}).items():
            yield f"tool:{t['function']['name']}.{k}", v["description"]
    for b in ("alf", "app"):
        for para in open(f"{base}/README.{b}.md").read().split("\n"):
            for ph in re.split(r"(?<=[.:;]) (?=[A-Z`])", para.strip()):
                if len(ph) > 40:
                    yield f"README.{b}", ph.lstrip("- ")


def origin(ph):
    key = ph[:60]
    out = subprocess.run(["git", "log", "--all", "--reverse", "--format=%h %ad", "--date=format:%d.%m", "-S", key],
                         capture_output=True, text=True).stdout.split("\n")
    return out[0] if out and out[0] else "?"


texts = []
for g in globs:
    for f in glob.glob(g, recursive=True):
        t = []
        for line in open(f):
            try:
                r = json.loads(line)
            except Exception:
                continue
            if r.get("type") == "turn":
                t.append((r.get("content") or "") + " " + (r.get("reasoning") or ""))
        texts.append(re.sub(r"\s+", " ", " ".join(t)).lower())

seen = set()
for where, ph in phrases():
    if ph in seen:
        continue
    seen.add(ph)
    w = re.sub(r"\s+", " ", ph.lower()).split()
    grams = {" ".join(w[i:i + 5]) for i in range(max(1, len(w) - 4))}
    cited = sum(any(g in t for g in grams) for t in texts)
    print(f"{where}\t{origin(ph)}\t{cited}/{len(texts)}\t{ph[:160]}")
