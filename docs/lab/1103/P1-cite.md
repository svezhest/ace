# P1 — писатель видит процитированные строки (`--cite`)

[Указатель проб](../INDEX.md) · хронология: [3.11](../days/1103.md) · как устроено — [README](../README.md)

<!-- LAB-1103.md:51–71 -->
### P1. Писатель видит процитированные строки (`--cite`, e4924d3)
- **Корень.** Писатель не видел ни одного реального значения, на котором проверяет своё условие: «никогда не истинно» — 31 правка, «не та форма данных» — 14 (§7).
- **Изменение.** Под наблюдением — строки logs/run_N.jsonl, на которые оно ссылается, как в файле (≤ 6 строк по ≤ 400 символов).
- **Стенд.** 6 входов (ALF n4_2, n0_1, n14_0; App n2_0, n0_2, n0_1 — наибольшее число верных находок по `j/*.json`), плечо obs против cite, seed 1.
  Задания `ed_<b>_<tag>_{obs,cite}`, затем `me_…`: кандидат на тех же задачах, что его родитель (seed и n из run.json родителя).
- **Мерка.** Процесс: в скольких сессиях правка ссылается на процитированное значение. Эффект: доля сработавших новых
  сообщений (`edit_stats`), сломанные, пары кандидат против родителя.
- **Ожидание.** Доля сработавших у cite выше, чем у obs (база дерева: obs 20/58). На 6 входах это различие, а не
  эффект.

- **Итог процесса, 02:40** (`editor/wb_stats.py runs/wbench_1103`). 5 входов из 6: ALF n0_1 потерян, см. «Дефект 1» ниже, перезапущен.

  | плечо | правок применено / попыток | запусков smoke | правок без smoke после них | конец по лимиту bash | минут модели |
  |---|---|---|---|---|---|
  | obs | 27/32 | 26 | 5 (ALF n4_2: 4, App n0_1: 1) | 4 из 5 | 143 |
  | cite | 30/40 | 28 | 0 | 3 из 5 | 195 |

  - Сессии cite на 36% дольше: первое сообщение больше. Отказов правок больше: 10 против 5.
  - «Цитата использована» (кусок ≥ 24 символов цитаты в ответах или правках): App 6/16 и 3/4, ALF 0/12 и 0/8. **Мерка негодна для ALF**: там процитированные значения короткие («step limit»). Снята, вывод — только по замеру.
- **Дефект 1 (мой), 02:40.** Домашний каталог писателя назывался `<тег>_<плечо>` без бенча, а тег n0_1 есть в обоих деревьях. Задание App n0_1 начинается с `rm -rf` своего каталога и стёрло сессии ALF n0_1 (obs, cite). Тот же дефект был в `wbench.sh`. Исправлено: `<бенч>_<тег>_<плечо>`; для готовых каталогов поставлены ссылки; `ed_alf_n0_1_{obs,cite}` перезапущены, их логи — `state/*.log.lost`. Плечо imp не задето: ALF n0_1 imp пишется в свой каталог (`alf_n0_1_imp → n0_1_imp`), App — в новый.

## Код

<!-- LAB-1103.md:72–122 -->
**Код пробы** (приписано 10.11). Из кода убран в a13b543: в develop осталась одна база. Последний коммит с этим кодом — 951bc3b (`git show 951bc3b:ФАЙЛ`); номера строк в листинге — по нему.

`--cite` (P1)

```python
# nrhsi/editor/inputs.py:12-13
CITE_CHARS = 400         # --cite: символов строки лога на цитату
CITE_LINES = 6           # --cite: строк на наблюдение

# nrhsi/editor/inputs.py:37-42
def review_root(tag):
    """Вид, который читал исследователь (его logs/run_N.jsonl), по строке meta лога сессии; None — нет на диске."""
    log = input_log(tag)
    meta = json.loads(open(log).readline())
    root = os.path.join(os.path.dirname(os.path.dirname(log)), "views", meta.get("view", ""))
    return root if os.path.isdir(f"{root}/logs") else None

# nrhsi/editor/inputs.py:45-66
def cited(evidence, root):
    """--cite (3.11): строки logs/run_N.jsonl, на которые ссылается evidence, как они есть в файле (обрезаны)."""
    out = []
    for e in evidence:
        ml = EV.EV_LIST_RE.match(e)
        m = None if ml else EV.CITE_RE.match(e)
        mh = EV.EV_HEAD_RE.match(e)
        path = (ml or m or mh).group(1) if (ml or m or mh) else None
        if not path or not EV.RUN_LOG_RE.match(os.path.normpath(path)) or not os.path.isfile(f"{root}/{path}"):
            continue
        lines = EV._read_log(f"{root}/{path}")
        if ml or m:
            nums = ([int(x) for x in ml.group(2).split(",")] if ml else
                    list(range(int(m.group(2)), int(m.group(3) or m.group(2)) + 1)))
        else:
            q = e[mh.end():].strip().strip("'\"`“”«»").strip()
            nums = EV._quote_lines(q, lines)[:2] if len(q) >= EV.QUOTE_MIN else []
        for x in nums:
            if 1 <= x <= len(lines) and len(out) < CITE_LINES:
                s = lines[x - 1]
                out.append(f"{path}:{x}: " + (s if len(s) <= CITE_CHARS else s[:CITE_CHARS] + " ..."))
    return out

# nrhsi/editor/inputs.py:79-81
lines = cited(r["evidence"], root) if root else []
if lines:
    part += "\nCited log lines, as the file has them:\n" + "\n".join(lines)

# nrhsi/editor/cli.py:300
first = IN.first_user_editor_obs(reports, IN.review_root(a.input) if a.cite else None)
```


## Связанные записи

- [3.11](../days/1103.md): §5 «Решения автора, 04:20»: писателя не мерить замером задач
- [3.11](../days/1103.md): §6 «Ручной разбор писателя, 05:00»: все 24 сессии obs/cite/imp/chk
- [3.11](../days/1103.md): «Ошибки дня, отмеченные автором» (§10)
