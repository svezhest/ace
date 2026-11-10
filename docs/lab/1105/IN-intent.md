# IN — намерение в edit (`--intent`)

[Указатель проб](../INDEX.md) · хронология: [5.11](../days/1105.md) · как устроено — [README](../README.md)

<!-- LAB-1103.md:1403–1419 -->
## Проба IN: намерение в edit (05.11; пользователь: «это thinking снаружи =) …пробуй и документируй»)
- Довод пользователя: поле, где ошибка ничего не стоит, заполняется бредом (у Opus — описание команды для пользователя). Поэтому у намерения есть цена: его сверяют с фактом.
- Коммит 7026793: `--intent` (с --rerun --auto-check):
  - edit получает обязательные expect_runs (array[int], прогоны logs/, ход которых правка меняет) и expect (что харнесс сделает там иначе); без них — стандартный отказ, правка не применяется;
  - после авто-проверки строка «Your expectation: runs … Runs that changed: … (passed) … Changed but not expected: … Expected but unchanged: …»;
  - при правке промпта: «the replay cannot tell which runs change».
  - Решает писатель, механика только показывает расхождение с его же утверждением.
- Проверено на готовых правках (02_GC_s5, 02_GC_s1, 05_GC_s4): разбор вывода rerun верен.
- Шаг 1: одна сессия 02_IN (AC + --intent, seed 1) — механика. Затем 10 наблюдений против AC (s1: 2/1/4/3).
- Мерка: заполнение полей (бред или по делу — руками); сколько раз «Changed but not expected» с удачными привёл к откату или сужению; вердикты.
- **Шаг 1 IN (02_IN, 13.5 мин, 24 bash):** механика работает.
  - Две правки без полей получили отказ («expect_runs: expected type: array[int], got: nothing»), дальше поля заполнены.
  - Поля по делу: правки комментариев помечены expect_runs=[], «clarify loop-detection comment»; сверка «Runs that changed: none» с этим согласна.
  - Сама сессия — x: изменены только комментарий и docstring.
  - Итог писателя — блеф против данных: «the harness now issues the warning… then the stand's guard detects the repeated reply and ends the episode». Сверка честно показала «none changed», но целью правки поведение не было.
  - Сбоев намерения нет; провал — в идее (согласие с «стенд сам оборвёт»).
- Шаг 2: остальные 9 наблюдений, seed 1.

*[…] строки этой записи между предыдущим куском и этим — в: [NV](NV-navigator.md), [GC25](GC25-given-code-25.md)*

<!-- LAB-1103.md:1448–1460 -->
- **Итог IN, 10 наблюдений** (AC + --intent, seed 1):
  - Вердикты:
    - 00 B (стоп по наблюдениям; тикет с 36, задеты 6 удачных);
    - 01 B; 02 x (только комментарии);
    - 03 B (проверка по выводу вместо кода, расходятся все 9 с вызова 3, «This will fail again» осталось);
    - 04 без правок; 05 x (у примера-вопроса убран answer, а строка «Remember» говорит, что ему answer нужен);
    - 06 без правок; 07 V; 08 x; 09 x (падение).
  - Итого V1 B3 x6, без правок 2. База AC s1: V2 P1 B4 x3.
  - Трение: первая правка без полей в 9 из 10 сессий (отказ, повтор). 06_IN: три отказа подряд и ни одной правки, а на 06 в остальных вариантах почти всегда V. Обязательное поле съело правку.
  - Чем заполнено: `expect_runs=[]` по умолчанию даже у живых правок (07_IN — V, но [] при изменившихся 6, 36; 00, 01, 02). То самое «поле, где ошибка дешёвая»: пустой список — самый дешёвый ответ.
  - Реакция на расхождение: ни одного отката или сужения после «Changed but not expected: … (passed)» (00, 01, 03). Исключение — 08_IN: ждал изменения в 40, четыре раза видел «Expected but unchanged: 40» и правил дальше (все четыре мёртвые).
  - Вывод: зеркало показано, но не принято. Согласие с собой (своя правка) сильнее, чем показанный факт. Обязательность полей мешает больше, чем помогает.

## Код

<!-- LAB-1103.md:1461–1552 -->
**Код пробы** (приписано 10.11). Из кода убран в a13b543: в develop осталась одна база. Последний коммит с этим кодом — 951bc3b (`git show 951bc3b:ФАЙЛ`); номера строк в листинге — по нему.

`--intent` (IN)

```python
# nrhsi/editor/prompt.py:114-116
INTENT_LINE = (" With each edit say what you expect it to do: expect_runs, the numbers of the recorded runs in logs/ "
               "whose course it changes ([] if none), and expect, what the harness will do differently in them. The "
               "checks after the edit compare this with the runs that did change.")

# nrhsi/editor/schema.py:65-78
def edit_schema():
    """--intent: edit с expect_runs и expect (ожидание правки, сверяется после авто-проверки)."""
    from . import cfg as C
    if not C.INTENT:
        return EDIT_SCHEMA
    f = json.loads(json.dumps(EDIT_SCHEMA["function"]))
    f["parameters"]["properties"]["expect_runs"] = {
        "type": "array", "items": {"type": "integer"},
        "description": "Numbers of the recorded runs in logs/ whose course this edit changes; [] if none"}
    f["parameters"]["properties"]["expect"] = {
        "type": "string", "description": "What the harness will do differently in those runs"}
    if not C.INTENT_OPT:
        f["parameters"]["required"] = f["parameters"]["required"] + ["expect_runs", "expect"]
    return {"type": "function", "function": f}

# nrhsi/editor/cli.py:170-175
if a.intent:
    assert a.auto_check and a.rerun and not a.rerun_tool, "--intent needs --auto-check --rerun"
    assert P.EDIT_TOOL_LINE in esys
    sig = "expect_runs?, expect?" if a.intent_opt else "expect_runs, expect"
    esys = esys.replace(P.EDIT_TOOL_LINE, P.EDIT_TOOL_LINE.replace("- edit(path, old_string, new_string)",
                        f"- edit(path, old_string, new_string, {sig})") + (P.INTENT_OPT_LINE if a.intent_opt else P.INTENT_LINE))

# nrhsi/editor/tools.py:75-88
if C.INTENT:
    er, ex = args.get("expect_runs"), args.get("expect")
    errs = []
    opt = C.INTENT_OPT and er is None and ex is None
    if not opt and (not isinstance(er, list) or not all(isinstance(x, int) and not isinstance(x, bool) for x in er)):
        errs.append(f"expect_runs: expected type: array[int], got: {GA.type_name(er)}")
    if not opt and (not isinstance(ex, str) or not ex.strip()):
        errs.append(f"expect: expected a non-empty string, got: {GA.type_name(ex)}")
    if errs:
        run.st["edit_fail"]["intent"] = run.st["edit_fail"].get("intent", 0) + 1
        res["edit"] = {"rel": args.get("path"), "fail": "intent", "applied": False}
        run.items.append({"path": args.get("path"), "fail": "intent", "call": run.st["tool_calls"],
                          "final": bool(run.final_left)})
        return "Error: edit not applied. " + "; ".join(errs) + ".", False

# nrhsi/editor/tools.py:102-104
if C.INTENT and args.get("expect_runs") is not None:
    text += "\n" + GA.intent_report(run, args["expect_runs"])
    rec["expect_runs"], rec["expect"] = args["expect_runs"], args.get("expect")

# nrhsi/editor/gate.py:103
HEAD = re.compile(r"(all \d+ runs|runs? [\d, ]+) \(")

# nrhsi/editor/gate.py:106-123
def changed_runs(full, root):
    """Строки-заголовки вывода rerun -> (изменившиеся прогоны, удачные, отличается ли промпт)."""
    res = [json.loads(l) for l in open(f"{root}/logs/results.jsonl")]
    every = [r["run"] for r in res]
    passed = {r["run"] for r in res if r.get("ok")}
    ch, prompt = set(), False
    for l in full.splitlines():
        if not l or l[0].isspace():
            continue
        m = HEAD.match(l)
        if not m:
            continue
        rs = every if m.group(1).startswith("all") else [int(x) for x in re.findall(r"\d+", m.group(1))]
        if "the prompt differs" in l:
            prompt = True
        elif "no changes" not in l:
            ch.update(rs)
    return ch, passed, prompt

# nrhsi/editor/gate.py:126-135
def intent_report(run, expect):
    """--intent: ожидание правки (expect_runs) против прогонов, что изменились в повторе."""
    ch, passed, prompt = changed_runs(run.last_rerun or "", run.root)
    if prompt:
        return ("Your expectation: runs " + (", ".join(map(str, expect)) or "none") + ". The prompt differs from the "
                "log, so every run may go differently from the start; the replay cannot tell which runs change.")
    fmt = lambda rs: ", ".join(f"{r} (passed)" if r in passed else str(r) for r in sorted(rs)) or "none"
    ex = set(expect)
    return (f"Your expectation: runs {fmt(ex)}. Runs that changed: {fmt(ch)}. Changed but not expected: {fmt(ch - ex)}. "
            f"Expected but unchanged: {fmt(ex - ch)}.")
```
