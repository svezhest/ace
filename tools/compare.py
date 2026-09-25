"""Сравнение двух снимков tools/trace.py: uv run python tools/compare.py OLD NEW.
Код возврата 1, если хоть один метод разошёлся."""
import difflib
import gzip
import json
import sys

HIDDEN = ("best", "iterations")


def load(path):
    path = str(path)
    with (gzip.open(path, "rt") if path.endswith(".gz") else open(path)) as f:
        return json.load(f)


def texts(trace):
    """Тексты записей по видам: порядок внутри вида сравнивается, чередование видов — нет."""
    out = {}
    for r in trace["memory"]:
        if r["kind"] not in HIDDEN:
            out.setdefault(r["kind"], []).append(r["text"])
    return out


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
            for kind in sorted(set(ma) | set(mb)):
                if ma.get(kind) != mb.get(kind):
                    print(f"   {kind}:", [t[:60] for t in ma.get(kind, [])[:3]], "\n   ->", [t[:60] for t in mb.get(kind, [])[:3]])
    return bad_methods


if __name__ == "__main__":
    sys.exit(bool(compare(load(sys.argv[1]), load(sys.argv[2]))))
