"""Процесс сессий писателя стенда: конец, правки, smoke, непроверенные правки, использованы ли цитаты входа.

  python3 editor/wb_stats.py runs/wbench_1103

«Цитата использована»: кусок ≥ 24 символов из строки блока «Cited log lines» первого сообщения встречается
в тексте ответов модели или в new_string правок (грубо: пересказ своими словами сюда не попадёт).
"""
import glob
import json
import os
import re
import sys


def pieces(first):
    if "Cited log lines" not in first:
        return []
    out = []
    for line in first.splitlines():
        m = re.match(r"logs/run_\d+\.jsonl:\d+: (.*)", line)
        if m:
            out += [x for x in re.findall(r'"([^"]{24,})"', m.group(1))]
    return out


rows = []
for f in sorted({os.path.realpath(p) for p in glob.glob(f"{sys.argv[1]}/*/logs/*.jsonl")}):   # каталоги и ссылки на них
    recs = [json.loads(x) for x in open(f)]
    meta = recs[0]
    end = [r for r in recs if r.get("type") == "end"]
    st = end[-1]["stats"] if end else {}
    text, smoke, ev = "", 0, []
    for r in recs:
        if r.get("type") != "turn":
            continue
        text += r.get("content") or ""
        for tc, res in zip(r.get("tool_calls") or [], r.get("results") or []):
            a = tc.get("arguments") or ""
            if tc.get("name") == "edit":
                text += a
                if (res.get("edit") or {}).get("applied"):
                    ev.append("e")
            elif tc.get("name") == "bash" and "tests/smoke.py" in a:
                smoke += 1
                ev.append("s")
            elif tc.get("name") == "bash" and "import" in a and "src" in a and "python3" in a:
                ev.append("i")
    unchecked = sum(1 for i, x in enumerate(ev) if x == "e" and "s" not in ev[i + 1:])
    ps = pieces(meta["first_user"])
    used = sum(1 for p in set(ps) if p[:24] in text)
    rows.append((os.path.basename(f)[:-6], (end[-1]["reason"] if end else "-")[:22], st.get("edits_applied"),
                 st.get("edits_attempted"), smoke, unchecked, ev.count("i"), f"{used}/{len(set(ps))}" if ps else "-",
                 st.get("bash_calls"), round(st.get("model_sec", 0) / 60, 1)))
print("| сессия | конец | правок прим./попыт. | smoke | без smoke после | python3 import src | цитат использовано | bash | мин |")
print("|---|---|---|---|---|---|---|---|---|")
for r in rows:
    print("| " + " | ".join(str(x) for x in (r[0], r[1], f"{r[2]}/{r[3]}", *r[4:])) + " |")
