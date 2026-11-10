# GC-1 — писатель без обзора (`--given-code`)

[Указатель проб](../INDEX.md) · хронология: [5.11](../days/1105.md) · как устроено — [README](../README.md)

<!-- LAB-1103.md:1099–1113 -->
## Проба GC-1: писатель без обзора (05.11, пользователь: «попробуй… по одному, каждую смотри внимательно»)
- Гипотеза: explore — ритуал, он не зависит от наблюдения (03_HT, 07_HT: README → весь src → results → много прогонов → поиск инструментов → свои заглушки); вердикты от лимита bash не зависят. Если код, на который ссылается наблюдение, даёт харнесс, писателю хватит 3 bash.
- Коммит c927867: `--given-code` (с --input-text). Под текстом наблюдения — код src/ вида по ссылкам `src/F:a-b` и `:a`: наименьшая функция, что содержит ссылку (≤60 строк), иначе ±8 строк; в .md ±4. Сухой прогон на всех 10, руками прочитаны 02, 04, 09 — фрагменты верные.
- Плечо GC: `--rerun --auto-check --bash-limit 3 --given-code`; системный промпт тот же (строка лимита — 3 bash, потом 3 финальных хода).
- Шаг 1: 02_GC_s1, 06_GC_s1 (класс А, один seed). Мерка процесса: на что ушли 3 bash; сколько правок, сделанных до конца bash; что показал авто-rerun; дошло ли до finish. Вердикт — руками.
- Ожидание: правки есть, сделаны на основе данного кода; V на 02 и 06 не реже, чем в базе (W1: 02 V, 06 V).
- Дальше, если механика в порядке: over-generate K=6 на 2 наблюдениях → механический фильтр rerun → судья L0 (×3, большинство) → все 10.
- **Итог GC-1:**
  - Механика в порядке: обе сессии дошли до правок, авто-проверка в ответе edit пришла.
  - Цена: 1.1 и 1.3 мин модели, пик 7–8K токенов. База W1 на тех же наблюдениях — 31 и 15 мин, 22–25K.
  - Ритуал остался, только сжался: все 3 bash — `cat README.md`, `cat src/harness.py` целиком, `cat bridge.py`. В 06 несколько cat склеены через `;` в один вызов. Данный код ритуал не отменяет; дешевле его делает лимит.
  - 02_GC_s1 → B: правка сравнивает с двумя прошлыми шагами (идея 01), повтор всё так же не исполняется; задеты 3 удачных. В базе 02 — V.
  - 06_GC_s1 → V: блок действия не из списка в harness.py (+хук +строка промпта); со старым промптом расходятся 19 прогонов, в том числе тикет 11, как у прежних V на 06.
- Фильтр (scratchpad b1/filt.py), сверка на 17 прочитанных сессиях блока 3: «нет правок / падение / тикет не задет» отсекает верно. Не видит правки, которые задевают только тикет и вредят там (02_STAC_s2, 07_AC_s2: насильный конец эпизода). Судья на удачных прогонах их тоже не увидит: дыра схемы.

## Код

<!-- LAB-1103.md:1114–1183 -->
**Код пробы** (приписано 10.11). Из кода убран в a13b543: в develop осталась одна база. Последний коммит с этим кодом — 951bc3b (`git show 951bc3b:ФАЙЛ`); номера строк в листинге — по нему.

`--given-code` (GC)

```python
# nrhsi/editor/inputs.py:93-99
def first_user_editor_text(path, src=None, files=False):
    """3.11, проба потолка формата: вместо блока наблюдений — готовый текст из файла, как есть.
    5.11 --given-code: src — src/ вида; под текстом — код, на который он ссылается (given_code).
    5.11 --given-files (абляция): под текстом — README.md и все файлы src/ целиком."""
    t = open(path).read().rstrip()
    extra = given_files(src) if src and files else given_code(t, src) if src else ""
    return t + extra + OBS_TAIL

# nrhsi/editor/inputs.py:114-115
REF = re.compile(r"(src/[\w.-]+)?:(\d+)(?:-(\d+))?")
GIVEN_PAD_MD, GIVEN_PAD_PY, GIVEN_MAX_DEF = 4, 8, 60    # строк вокруг ссылки в .md / вне функции в .py; длиннее — не целиком

# nrhsi/editor/inputs.py:118-128
def cited_ranges(text):
    """Ссылки src/F:a-b и короткие :a (на последний названный файл) -> {F: [(a, b)]}."""
    out, cur = {}, None
    for m in REF.finditer(text):
        if m.group(1):
            cur = m.group(1)
        if cur is None:
            continue
        a = int(m.group(2))
        out.setdefault(cur, []).append((a, int(m.group(3) or a)))
    return out

# nrhsi/editor/inputs.py:131-140
def widen_py(code, a, b):
    """Строки a..b -> наименьшая функция, что их содержит (если не длиннее GIVEN_MAX_DEF), иначе ±GIVEN_PAD_PY."""
    best = None
    for n in ast.walk(ast.parse(code)):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            lo = min([n.lineno] + [d.lineno for d in n.decorator_list])
            if lo <= a and b <= n.end_lineno and n.end_lineno - lo + 1 <= GIVEN_MAX_DEF:
                if best is None or n.end_lineno - lo < best[1] - best[0]:
                    best = (lo, n.end_lineno)
    return best or (a - GIVEN_PAD_PY, b + GIVEN_PAD_PY)

# nrhsi/editor/inputs.py:143-165
def given_code(text, src):
    """Код src/, на который ссылается текст наблюдения, как он есть: функции целиком, иначе строки вокруг ссылки."""
    parts = []
    for f, rs in cited_ranges(text).items():
        path = f"{src}/{f[4:]}"
        if not os.path.exists(path):
            continue
        code = open(path).read()
        lines = code.splitlines()
        wide = sorted(widen_py(code, a, b) if f.endswith(".py") else (a - GIVEN_PAD_MD, b + GIVEN_PAD_MD) for a, b in rs)
        merged = []
        for a, b in wide:
            a, b = max(1, a), min(len(lines), b)
            if merged and a <= merged[-1][1] + 1:
                merged[-1] = (merged[-1][0], max(merged[-1][1], b))
            else:
                merged.append((a, b))
        lang = "python" if f.endswith(".py") else ""
        for a, b in merged:
            parts.append(f"{f}, lines {a}-{b}:\n```{lang}\n" + "\n".join(lines[a - 1:b]) + "\n```")
    if not parts:
        return ""
    return "\n\n## The code these references point to, as it is now in src/\n\n" + "\n\n".join(parts)
```


## Связанные записи

- [5.11](../days/1105.md): «Принцип от пользователя: опора, не клетка»: GC — клетка
