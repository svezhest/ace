# 08_IO_R — воскрешение 08_IO (`--resume`)

[Указатель проб](../INDEX.md) · хронология: [6.11](../days/1106.md) · как устроено — [README](../README.md)

<!-- LAB-1103.md:1890–1899 -->
### Воскрешение 08_IO (6.11)
- Случай: после правки авто-проверка показала «all 29 runs: no changes». Писатель: «my hook must not be triggering», и в ходе 21 написал отладку, которая печатает `any_repeat` для run 40 на шагах 3–11. Она показала бы, что условие — тавтология. Но bash к этому моменту кончился.
- Механика `--resume LOG --resume-turn I --resume-bash N` (`nrhsi/editor/resume.py`):
  - история (ходы, выводы, заметки) берётся из лога до хода I;
  - применённые правки повторяются на свежей копии;
  - ход I — та же реплика модели, но её вызовы исполняются заново;
  - лимит bash = израсходованные + N, потом заметка «bash is available again: N more calls».
  - Сверено: src после повтора правок совпадает с итоговым src 08_IO; системный промпт и первое сообщение совпадают с логом (в рантайме это проверяет assert).
- Сессия `wv_08_IO_R`: ход 21, +15 bash. Вопросы: увидит ли он тавтологию по своему выводу; исправит ли условие; что сделает дальше с «no changes».

<!-- LAB-1103.md:1988–2005 -->
### Воскрешение 08_IO: итог (6.11, 03:10)
`runs/wvar_1104/08_IO_R`: с хода 21 ещё 15 bash, израсходовал 14, закончил finish.
- **Ход 21.** Его отладка выполнена и напечатала `any_repeat=True` на всех шагах 3–11, то есть тавтологию видно в его же выводе.
- **Ход 22.** «The logic is correct — at i=11, distinct=3…». Смотрит только на distinct, строку `any_repeat=True` не читает. Вывод опять раньше факта.
- **Ходы 23–28 — настоящая работа.**
  - Прогнал своё условие на всех удачных прогонах. С окном 4 ложных срабатываний 7: «open drawer 2, open drawer 2, open drawer 3…», «take book 1 / book 2».
  - Вывел окна удачных, искал отличие. Посчитал «самый длинный застой»: run 40 — 37 шагов, остальные 0.
  - Нашёл окно 5, при котором срабатывают только 40 и 39 (у 39 длина 1, он назвал это «a one-off»).
- **Правка (ход 29).**
  - Окно 8 → 5.
  - `if any(...): return None` → `if not any(...): return None`. Это та же тавтология, только наоборот: проверка наблюдений теперь пустая, всегда проходит.
  - Фактически условие — «≤2 разных действия за 5 шагов». Его симуляции считали ту же тавтологию, так что симуляция и код совпали, а проверка наблюдений не работала ни там, ни там.
- **Rerun:** «runs 39, 40 (1 failed, 1 passed): diverges at model call (14, 28)».
  - Ход 30: «fires exactly on runs 39 and 40 (the stuck-loop failures)».
  - Ход 34: «only the two stuck-loop runs (39, 40)… All 27 other runs (including all successful ones) never trigger».
  - Run 39 прошёл. Это написано и в rerun («1 passed»), и в его собственном списке удачных (ход 23). Желаемое за действительное — третий раз в одной сессии.
- **Вердикт.** Впервые живая правка на 08 (за всю серию до этого 0). Подсказка, а не стоп. Задет удачный 39, где похожее чередование «take book 1 / take book 2». По нашей мерке B (мягкий: подсказка, не конец эпизода).
- **Что показал bash.** Он умеет проверять условие на данных и делает это много и толково, когда есть чем. Но свой вывод читает избирательно: `any_repeat=True` пропустил, «1 passed» переименовал в «stuck-loop failures». Нехватка bash не единственная беда, но в 08_IO она была главной: без воскрешения правка мёртвая, с ним живая.

## Код

<!-- LAB-1103.md:1900–1959 -->
**Код пробы** (приписано 10.11). Из кода убран в a13b543: в develop осталась одна база. Последний коммит с этим кодом — 951bc3b (`git show 951bc3b:ФАЙЛ`); номера строк в листинге — по нему.

`--resume LOG --resume-turn T --resume-bash N` (08_IO_R; 9.11 — PKR). `load` и `apply_edits` остались в `editor/fork.py`

```python
# nrhsi/editor/cli.py:204-210
resume = None
if a.resume:
    from . import resume as RS
    recs = RS.load(a.resume)
    print(json.dumps({"resume_edits_replayed": RS.apply_edits(recs, a.resume_turn, root)}), flush=True)
    resume = RS.restorer(recs, a.resume_turn, a.resume_bash)
    summary["resume"] = {"log": a.resume, "turn": a.resume_turn, "bash": a.resume_bash}

# nrhsi/editor/resume.py:32-73
def restorer(recs, upto, extra_bash):
    meta = recs[0]

    def restore(run):
        assert run.messages[0]["content"] == meta["system"], "system prompt differs from the log"
        assert run.messages[1]["content"] == meta["first_user"], "first message differs from the log"
        st = run.st
        for r in recs[1:]:
            if r.get("type") == "note":
                run.messages.append({"role": "user", "content": r["text"]})
            elif r.get("type") == "turn" and r["i"] < upto:
                amsg = {"role": "assistant", "content": r.get("content") or ""}
                if r["tool_calls"]:
                    amsg["tool_calls"] = [{"id": f"call_{r['i']}_{j}", "type": "function",
                                           "function": {"name": c["name"], "arguments": c["arguments"]}}
                                          for j, c in enumerate(r["tool_calls"])]
                run.messages.append(amsg)
                for j, res in enumerate(r["results"]):
                    run.messages.append({"role": "tool", "tool_call_id": f"call_{r['i']}_{j}", "content": res["shown"]})
                st["turns"] = r["i"]
                st["tool_calls"] += len(r["tool_calls"])
                st["bash_calls"] += sum(c["name"] == "bash" and "no longer available" not in str(res.get("shown"))
                                        for c, res in zip(r["tool_calls"], r["results"]))
            elif r.get("type") == "turn" and r["i"] == upto:
                break
        cut = next(r for r in recs if r.get("type") == "turn" and r["i"] == upto)
        # заметки между последним ходом < upto и ходом upto уже добавлены циклом (идут в логе до него)
        run.final_left, run.final_why = 0, None
        run.bash_limit = st["bash_calls"] + extra_bash
        run.w({"type": "resume", "from_turn": upto, "bash_used": st["bash_calls"], "bash_limit": run.bash_limit})
        st["turns"] = upto
        amsg = {"role": "assistant", "content": cut.get("content") or ""}
        amsg["tool_calls"] = [{"id": f"call_{upto}_{j}", "type": "function",
                               "function": {"name": c["name"], "arguments": c["arguments"]}}
                              for j, c in enumerate(cut["tool_calls"])]
        run.messages.append(amsg)
        rec = {"type": "turn", "i": upto, "replayed": True, "content": cut.get("content"),
               "tool_calls": cut["tool_calls"], "results": []}
        TU.run_calls(run, amsg, rec)
        run.w(rec)
        run.note_user(f"bash is available again: {run.bash_limit - st['bash_calls']} more calls.")
    return restore
```
