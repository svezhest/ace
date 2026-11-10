# P6 — smoke показывает вызовы (`--smoke-calls`)

[Указатель проб](../INDEX.md) · хронология: [3.11](../days/1103.md) · как устроено — [README](../README.md)

<!-- LAB-1103.md:148–155 -->
### P6. Smoke показывает вызовы (`--smoke-calls`, 7a6f00d)
- **Корень** (из находки P2): форма `ctx`, `history`, ответа модели и результата вспомогательных функций нигде не видна; `call_hook` молча глотает любое исключение хука (`except Exception: return None`).
- **Изменение.** `tests/calls.py` (`smoke/calls.py`) оборачивает функции модулей harness и hooks, кроме `run`. После первого сценария smoke печатает для каждой функции число вызовов, форму аргументов (снята до вызова) и результата первого вызова, первое исключение с трассой — также пойманное вызывающим. После остальных сценариев — только счёт и исключения. Строка в README копии. Без флага smoke.py и README те же байт в байт.
- **Проверка на узлах дерева.** ALF n4: `harness.action_of … returned: tuple[1] of str '(stub action 1)'` — ровно дефект, из-за которого правки n4 мёртвые (§6 NIGHT-1101). Видна и форма `stalled(history)`. Длина вывода ALF 5.5 тыс. символов, App 5.8 тыс. — меньше предела bash писателя (8000).
- **Задания.** `ed_<b>_<tag>_sc` × 6.
- **Мерка.** Процесс: ссылается ли писатель на строки вызовов (имя функции + «returned» / «raised») в ответах; число правок, после которых форма аргументов проверена. Эффект — сработавшие сообщения, пары.
- **Ожидание.** На ALF n4_2 хотя бы одна сессия заметит `tuple[1]`. Доля «не та форма данных» падает.

<!-- LAB-1103.md:433–434 -->
## 7. P4 и P6 — ручной разбор, 06:00
- **P6:** писатель видел строки вызовов, но ни разу их не использовал; поломано 1 из 6, пусто 1. Таблица — `docs/READ-writer-1103.md`.

## Код

<!-- LAB-1103.md:156–274 -->
**Код пробы** (приписано 10.11). Из кода убран в a13b543: в develop осталась одна база. Последний коммит с этим кодом — 951bc3b (`git show 951bc3b:ФАЙЛ`); номера строк в листинге — по нему.

`--smoke-calls` (P6)

```python
# nrhsi/editor/work.py:117-129
SMOKE_CALLS_README = (" After each scenario it lists the functions of src/harness.py and src/hooks.py that were called "
                      "and how many times, with the exceptions raised in them, also those that a caller catches; after "
                      "the first scenario also the arguments and the return value of each function's first call.")
LOOP = "    for n, (desc, Ep, script, mk) in enumerate(scenarios(), 1):\n"
TAIL = "            print(line)\n\n\nif __name__"


def smoke_calls(src):
    """--smoke-calls (3.11): в копию smoke — трассировка вызовов (smoke/calls.py), после каждого сценария."""
    assert src.count(LOOP) == 1 and src.count(TAIL) == 1
    src = src.replace(LOOP, "    import calls\n    import hooks\n    calls.install(harness, hooks)\n" + LOOP +
                      "        calls.reset()\n")
    return src.replace(TAIL, "            print(line)\n        for line in calls.lines(full=n == 1):\n            print(line)\n\n\nif __name__")

# nrhsi/editor/work.py:191-192
readme += SMOKE_README if not C.SMOKE_CALLS else SMOKE_README.replace(
    "or the error. ", "or the error." + SMOKE_CALLS_README + " ")

# nrhsi/editor/work.py:202-204
if C.SMOKE_CALLS:
    sm = smoke_calls(sm)
    shutil.copy(f"{C.SMOKE}/calls.py", f"{td}/calls.py")

# nrhsi/editor/smoke/calls.py:1-86
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
    if hasattr(x, "__dataclass_fields__") and not isinstance(x, type):
        if depth > 1:
            return f"{type(x).__name__}(...)"
        return f"{type(x).__name__}(" + ", ".join(f"{k}={shape(getattr(x, k), depth + 1)}" for k in x.__dataclass_fields__) + ")"
    if isinstance(x, type) or callable(x):
        return getattr(x, "__name__", f"{type(x).__name__} object")
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
```


## Связанные записи

- [3.11](../days/1103.md): §6 «Ручной разбор писателя, 05:00»
