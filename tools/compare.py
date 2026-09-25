"""Сравнение трасс: uv run python tools/compare.py [REF] NEW; REF по умолчанию tools/ref_trace.json(.gz).
Код возврата 1, если хоть один метод разошёлся."""
import difflib
import gzip
import json
import sys
from pathlib import Path

HIDDEN = ("best", "iterations")


def load(path):
    path = str(path)
    with (gzip.open(path, "rt") if path.endswith(".gz") else open(path)) as f:
        return json.load(f)


def default_ref():
    here = Path(__file__).parent
    return next(p for p in (here / "ref_trace.json.gz", here / "ref_trace.json") if p.exists())


def texts(trace):
    return [r["text"] for r in trace["memory"] if r["kind"] not in HIDDEN]


def compare(a, b):
    bad_methods = []
    for name in b:
        if name not in a:
            print(name, "нет в эталоне")
            continue
        ca, cb = a[name]["calls"], b[name]["calls"]
        ma, mb = texts(a[name]), texts(b[name])
        bad = next((i for i, (x, y) in enumerate(zip(ca, cb)) if x != y), None)
        if bad is None and len(ca) == len(cb) and ma == mb and a[name]["summary"]["correct"] == b[name]["summary"]["correct"]:
            print(f"{name:16} OK  calls={len(cb)}")
            continue
        bad_methods.append(name)
        print(f"{name:16} DIFF calls {len(ca)} vs {len(cb)}, memory {'same' if ma == mb else 'differs'}")
        if bad is not None:
            x, y = ca[bad], cb[bad]
            for k in x:
                if x[k] != y.get(k):
                    print(f"  call {bad} field {k}:")
                    if isinstance(x[k], str):
                        for line in list(difflib.unified_diff(x[k].splitlines(), y[k].splitlines(), lineterm="", n=1))[:14]:
                            print("   ", line[:160])
                    else:
                        print("   ", x[k], "->", y.get(k))
        elif ma != mb:
            print("  ", ma[:3], "\n  ", mb[:3])
    return bad_methods


if __name__ == "__main__":
    ref, new = (sys.argv[1], sys.argv[2]) if len(sys.argv) > 2 else (default_ref(), sys.argv[1])
    sys.exit(bool(compare(load(ref), load(new))))
