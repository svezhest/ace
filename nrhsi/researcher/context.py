"""Политики контекста: перед ходом — очистка старых выводов (заглушки) или сжатие (сводка модели)."""
import json
import time

from . import cfg as C
from . import prompt as P
from . import model as M


def before_turn(run, snap_name, resume):
    """CLEAR_AT достигнут вне финала -> снимок (SNAPSHOT_DIR) и сжатие или очистка."""
    if C.CLEAR_AT is not None and run.est() >= C.CLEAR_AT and not run.final_left:
        if C.SNAPSHOT_DIR and not resume:
            run.snapshot(snap_name)
        compact(run) if C.COMPACT else clear_old(run)


def stub_for(run, idx):
    c = run.messages[idx]["content"]
    call, cmd = run.tool_meta.get(idx, (None, ""))
    return C.STUB.format(lines=c.count("\n") + 1, chars=len(c), call=call, cmd=" ".join(str(cmd).split())[:200])


def clear_old(run):
    """Старые выводы инструментов -> заглушка (как clear_tool_uses / prune в кодинг-харнессах).
    Чистим пачкой, чтобы префикс-кэш сервера сбрасывался редко. v3b: CLEAR_TO — до какой оценки чистить
    (от старых к новым), CLEAR_AT_LEAST — минимум освобождаемого, иначе история не трогается."""
    plan, freed = [], 0
    est0 = run.est()
    for idx in (run.tool_msgs[:-C.KEEP_RESULTS] if C.KEEP_RESULTS else run.tool_msgs):
        if idx in run.cleared:
            continue
        if C.CLEAR_TO is not None and est0 - freed <= C.CLEAR_TO:
            break
        m = run.messages[idx]
        if len(m["content"]) < 400:
            continue
        stub = stub_for(run, idx)
        plan.append((idx, stub))
        freed += M.est_tokens(m["content"]) - M.est_tokens(stub)
    if not plan or freed < C.CLEAR_AT_LEAST:
        if plan:
            run.w({"type": "note", "text": f"[harness] clear skipped: would free ~{freed} < {C.CLEAR_AT_LEAST}"})
        return 0
    for idx, stub in plan:
        run.messages[idx]["content"] = stub
        run.cleared.add(idx)
    run.last_prompt -= freed
    run.st["clears"] += 1
    run.st["cleared_results"] += len(plan)
    run.w({"type": "note", "text": f"[harness] cleared {len(plan)} old tool outputs, ~{freed} tokens",
           "cleared_calls": [run.tool_meta.get(i, (None,))[0] for i, _ in plan]})
    return len(plan)


def _summary(run):
    """Просьба о сводке -> (сводка, ответ, ошибка, попыток, сек)."""
    t0 = time.time()
    # S4: без tools префикс шаблона другой -> кэш не берётся (233 с на 45K); те же tools.
    # S8: с tools модель ответила одним вызовом без текста -> tool_choice "none" (воркер держит tools в промпте)
    # и одна повторная просьба, если текста всё равно нет.
    req = [{"role": "user", "content": P.COMPACT_REQ}]
    summary, r, perr, tries = "", None, None, 0
    for extra in ([], [{"role": "user", "content": "Write the summary now, as plain text."}]):
        tries += 1
        resp, err = M.chat(run.messages + req + extra, run.temp, run.seed + 100000 + run.st["turns"] + tries,
                           P.TOOLS, "none")
        r, perr = (None, err) if err else M.parse_response(resp)
        summary = ((r or {}).get("content") or "").strip()
        if summary or err:
            break
    return summary, r, perr, tries, time.time() - t0


def _cut_history(run, cut):
    """Сообщения [2, cut) -> одно (индекс 2): сдвиг индексов в учёте выводов. -> номера убранных вызовов."""
    off = cut - 3
    removed_calls = [run.tool_meta.get(i, (None,))[0] for i in run.tool_msgs if i < cut]
    run.tool_msgs[:] = [i - off for i in run.tool_msgs if i >= cut]
    tm = {i - off: v for i, v in run.tool_meta.items() if i >= cut}
    run.tool_meta.clear()
    run.tool_meta.update(tm)
    sc = {k_: (v[0], v[1] - off) for k_, v in run.seen_cmds.items() if v[1] >= cut}
    run.seen_cmds.clear()
    run.seen_cmds.update(sc)
    cl = {i - off for i in run.cleared if i >= cut}
    run.cleared.clear()
    run.cleared.update(cl)
    return removed_calls


def compact(run):
    """A2 «сжатие»: модель пишет сводку; всё до хода, которому принадлежит KEEP_RESULTS-й с конца вывод,
    заменяется одним user-сообщением со сводкой и списком записанных report. Неудача -> обычная очистка."""
    st, messages = run.st, run.messages
    if len(run.tool_msgs) <= C.KEEP_RESULTS:
        return 0
    cut = run.tool_msgs[-C.KEEP_RESULTS] if C.KEEP_RESULTS else len(messages)
    while cut > 2 and messages[cut]["role"] != "assistant":
        cut -= 1
    if cut <= 2:
        return clear_old(run)
    summary, r, perr, tries, dt = _summary(run)
    st["model_sec"] += dt
    if not summary:
        run.w({"type": "note", "text": f"[harness] compaction failed ({perr or 'empty summary'}); clearing instead",
               "sec": round(dt, 1)})
        return clear_old(run)
    st["gen_tokens"] += r["usage"].get("completion_tokens") or 0
    rep_list = "\n".join(f"#{i + 1} ({x['kind']}): {x['observation']}" for i, x in enumerate(run.reports)) or "(none yet)"
    head = {"role": "user", "content": "[Earlier messages were removed from your context to save space. "
            f"Your summary of them:]\n\n{summary}\n\n[Findings recorded so far with report:]\n{rep_list}"}
    removed_calls = _cut_history(run, cut)
    messages[:] = messages[:2] + [head] + messages[cut:]
    run.last_prompt, run.pending = M.est_tokens(json.dumps(messages, ensure_ascii=False)), 0
    st["compactions"] += 1
    run.w({"type": "compact", "turn": st["turns"], "sec": round(dt, 1), "usage": r["usage"],
           "finish_reason": r["finish_reason"], "summary": summary, "summary_had_calls": bool(r["calls"]),
           "removed_calls": removed_calls, "removed_msgs": cut - 2, "est_after": run.last_prompt, "tries": tries,
           "reports_listed": len(run.reports)})
    return len(removed_calls)
