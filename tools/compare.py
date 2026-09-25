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


def first_difference(calls_a, calls_b):
    """Номер первого вызова, который отличается (в общей части); None — общая часть совпала."""
    for i, (x, y) in enumerate(zip(calls_a, calls_b)):
        if x != y:
            return i
    return None


def show_call_diff(i, x, y):
    """Поля вызова i, которыми снимки расходятся: строки — диффом, прочее — было -> стало."""
    for field in x:
        if x[field] == y.get(field):
            continue
        print(f"  call {i} field {field}:")
        if isinstance(x[field], str):
            diff = difflib.unified_diff(x[field].splitlines(), y[field].splitlines(), lineterm="", n=1)
            for line in list(diff)[:14]:
                print("   ", line[:160])
        else:
            print("   ", x[field], "->", y.get(field))


def show_memory_diff(ma, mb):
    """Виды записей, которые расходятся: первые три текста каждого снимка."""
    for kind in sorted(set(ma) | set(mb)):
        if ma.get(kind) != mb.get(kind):
            before = [t[:60] for t in ma.get(kind, [])[:3]]
            after = [t[:60] for t in mb.get(kind, [])[:3]]
            print(f"   {kind}:", before, "\n   ->", after)


def compare(a, b):
    """Методы снимка b против эталона a; -> имена разошедшихся."""
    bad_methods = []
    for name in b:
        if name not in a:
            print(name, "нет в эталоне")
            continue
        ca, cb = a[name]["calls"], b[name]["calls"]
        ma, mb = texts(a[name]), texts(b[name])
        bad = first_difference(ca, cb)
        same = (bad is None and len(ca) == len(cb) and ma == mb
                and a[name]["summary"]["correct"] == b[name]["summary"]["correct"])
        if same:
            print(f"{name:16} OK  calls={len(cb)}")
            continue
        bad_methods.append(name)
        print(f"{name:16} DIFF calls {len(ca)} vs {len(cb)}, memory {'same' if ma == mb else 'differs'}")
        if bad is not None:
            show_call_diff(bad, ca[bad], cb[bad])
        elif ma != mb:
            show_memory_diff(ma, mb)
    return bad_methods


if __name__ == "__main__":
    sys.exit(bool(compare(load(sys.argv[1]), load(sys.argv[2]))))
