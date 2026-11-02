"""Calls of the functions in src/harness.py and src/hooks.py during a smoke scenario: how many times each was
called, the arguments and the return value of its first call (types and short values), and the exceptions raised
in it, with the traceback, also those that a caller catches."""
import functools
import traceback
import types

SHOW = 50
calls = {}       # name -> {"n", "args": форма аргументов первого вызова, "ret": форма его результата, "exc", "n_exc"}
order = []


def shape(x, depth=0):
    if isinstance(x, dict):
        if depth > 1:
            return f"dict[{len(x)}]"
        return "{" + ", ".join(f"{k!s}: {shape(v, depth + 1)}" for k, v in list(x.items())[:12]) + \
            (", ..." if len(x) > 12 else "") + "}"
    if isinstance(x, (list, tuple)):
        t = type(x).__name__
        return f"{t}[{len(x)}]" + (f" of {shape(x[0], depth + 1)}" if x and depth <= 1 else "")
    if not isinstance(x, (str, int, float, bool, type(None), bytes)):
        return f"{type(x).__name__} object"
    r = repr(x)
    return f"{type(x).__name__} {r if len(r) <= SHOW else r[:SHOW] + '...'}"


def wrap(mod, name, fn):
    key = f"{mod.__name__}.{name}"

    @functools.wraps(fn)
    def w(*a, **k):
        c = calls.setdefault(key, {"n": 0, "args": None, "ret": None, "exc": [], "n_exc": 0})
        if not c["n"]:
            order.append(key)
            c["args"] = ", ".join([shape(x) for x in a] + [f"{n}={shape(v)}" for n, v in k.items()])   # до вызова
        c["n"] += 1
        try:
            out = fn(*a, **k)
        except Exception as e:  # noqa: BLE001
            c["n_exc"] += 1
            if not c["exc"]:
                tb = [f for f in traceback.extract_tb(e.__traceback__) if not f.filename.endswith("calls.py")]
                c["exc"].append("".join(traceback.format_list(tb)) + "".join(traceback.format_exception_only(type(e), e)))
            raise
        if c["n"] == 1:
            c["ret"] = shape(out)
        return out
    return w


def install(*mods):
    for m in mods:
        for name, fn in list(vars(m).items()):
            if isinstance(fn, types.FunctionType) and fn.__module__ == m.__name__ and name != "run":
                setattr(m, name, wrap(m, name, fn))


def reset():
    calls.clear()
    order.clear()


def lines(full=True):
    """full — с аргументами и результатом первого вызова; иначе — только число вызовов и исключения."""
    if not full:
        out = ["  calls: " + ", ".join(f"{k} {calls[k]['n']}" + (f" (raised {calls[k]['n_exc']})" if calls[k]["n_exc"] else "")
                                       for k in order)]
    else:
        out = ["  calls (functions of src/harness.py and src/hooks.py, in the order of their first call):"]
    for key in order:
        c = calls[key]
        if full:
            out.append(f"    {key}: {c['n']} calls" + (f", raised {c['n_exc']} times" if c["n_exc"] else ""))
            out.append(f"      first call: ({c['args']})")
            if c["ret"] is not None:
                out.append("      returned: " + c["ret"])
        for e in c["exc"]:
            out.append("      first exception:\n" + "\n".join("        " + x for x in e.rstrip().splitlines()[-8:]))
    return out
