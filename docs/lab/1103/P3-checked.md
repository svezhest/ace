# P3 — правка без проверки не применяется (`--checked`)

[Указатель проб](../INDEX.md) · хронология: [3.11](../days/1103.md) · как устроено — [README](../README.md)

<!-- LAB-1103.md:275–285 -->
### P3. Правка без проверки не применяется (`--checked`, c0775da)
- **Корень.** В 51 сессии деревьев 70 из 314 применённых правок (22%) не проверены ни одним запуском smoke; 37 из них — в финальных ходах (`editor/unchecked.py`).
- **Изменение.** В финальных ходах `edit` → «Error: edit not applied: no bash calls left to check it. Call finish.». Строка про лимит в промпте сказана в тех же словах.
- **Задания.** `ed_<b>_<tag>_chk` × 6.
- **Мерка.** Процесс: число правок в финальных ходах (по построению 0 применённых), число отказов «unchecked».
  Перераспределение: проверяет ли писатель раньше (smoke до 25-го bash). Эффект — после замера.
- **Ожидание.** Число применённых правок упадёт на 10–20%, доля сработавших не упадёт.
- **Итог процесса, промежуточный, 03:55** (3 из 6 сессий; App идут). Правок без smoke после — 0 во всех трёх: механизм включился. Все три кончились вызовом finish самим писателем, а не принудительно по лимиту bash (у obs принудительно 4 из 6).
  - ALF n4_2: 4/4 правки, 5 smoke, 27 мин. ALF n14_0: 1/5 правок (отказы: 3 — args, 1 — unchecked), 4 smoke.
  - **ALF n0_1: 0 правок, 9 bash, 2.1 мин, finish с ложным отчётом**: «I confirmed the root causes… I implemented the fixes: 1. In harness.py: execute ALL take_action…». Ни одного edit не было. Связь с флагом не установлена: сессия кончилась до финальных ходов, отказ «unchecked» не выдавался. Это тот же класс, что «верит done» у ревьювера — теперь у писателя о себе.

## Код

<!-- LAB-1103.md:286–311 -->
**Код пробы** (приписано 10.11). Из кода убран в a13b543: в develop осталась одна база. Последний коммит с этим кодом — 951bc3b (`git show 951bc3b:ФАЙЛ`); номера строк в листинге — по нему.

`--checked` (P3)

```python
# nrhsi/editor/prompt.py:102-103
CHECKED_LIMIT_LINE = ("- bash can be called BASH_LIMIT times; after that edits can no longer be checked and are not applied: "
                      "only finish remains, and the session ends.")

# nrhsi/editor/cli.py:141-143
if a.checked:
    esys = esys.replace(P.fill(P.LIMIT_LINE), P.fill(P.CHECKED_LIMIT_LINE))
    assert P.fill(P.CHECKED_LIMIT_LINE) in esys

# nrhsi/editor/tools.py:70-74
if C.CHECKED and run.final_left:
    run.st["edit_fail"]["unchecked"] = run.st["edit_fail"].get("unchecked", 0) + 1
    res["edit"] = {"rel": args.get("path"), "fail": "unchecked", "applied": False}
    run.items.append({"path": args.get("path"), "fail": "unchecked", "call": run.st["tool_calls"], "final": True})
    return "Error: edit not applied: no bash calls left to check it. Call finish.", False

# nrhsi/editor/phase.py:11
tail = ("Edits can no longer be checked, so they are not applied: call finish." if run.role == "editor" and C.CHECKED else
```


## Связанные записи

- [3.11](../days/1103.md): §6 «Ручной разбор писателя, 05:00»
- [ST, C30, AC, RT, SC, RT2, STAC](../1104/ST-AC-RT-SC-blocks.md): C30 (`--bash-limit 30 --checked`) — блок 1
- [5.11](../days/1105.md): «Пробы с исходом по построению»: «правок без smoke после — 0» — ноль по построению
