"""Логи вида -> поток событий (одна строка = одно событие), по готовым трассам и src, на котором они получены.

  python3 tools/to_events.py --bench appworld --view appworld/view --out appworld/view_ev

События (поле "event"):
  bridge   — вызов моста: fill (подстановки в шаблон промпта), reset, execute / step (что ушло в среду);
             end — как эпизод кончился на уровне моста (finished, step limit, ...), без оценки
  prompt   — сообщение, которое харнесс собрал из src/starting_prompt.md (после подстановок моста)
  env      — сообщение с результатом моста, как его получила модель
  model    — ответ модели
  harness  — прочие сообщения харнесса (файлы src/*.md)
Поля "message" по порядку = разговор, как его видела модель (байт в байт). Ничего не дописывается в тексты."""
import argparse
import json
import re
import shutil
from pathlib import Path

# reason из results.jsonl -> конец эпизода на уровне моста. Оценка (success / wrong result) сюда не идёт:
# мост знает только, что эпизод закончен (AppWorld: complete_task; ALFWorld: среда сама закрыла эпизод).
# Ошибка -> reason "error" и detail (repeated action — правило самого бенчмарка, AgentBench ALFWorld).
END = {"success": {"reason": "finished"}, "wrong result": {"reason": "finished"},
       "step limit": {"reason": "step limit"}, "harness stopped early": {"reason": "stopped"},
       "repeated action": {"reason": "error", "detail": "repeated action"},
       "harness error": {"reason": "error", "detail": "harness error"},
       "runner error": {"reason": "error", "detail": "runner error"}}

SLOT = re.compile(r"\{\{\s*([\w.]+)\s*\}\}")


def slots_of(template, text):
    """Значения слотов {{ x }} шаблона по заполненному тексту -> {имя: значение} (или None, если не совпало)."""
    parts = SLOT.split(template)
    rx = "".join(re.escape(p) if i % 2 == 0 else r"(.*?)" for i, p in enumerate(parts)) + r"\Z"
    m = re.match(rx, text, flags=re.DOTALL)
    if not m:
        return None
    names = parts[1::2]
    out = {}
    for n, v in zip(names, m.groups()):
        out.setdefault(n, v)
    return out


def split_roles(text):
    """Как text_to_messages в харнессе AppWorld: куски шаблона по маркерам USER:/ASSISTANT:/SYSTEM:."""
    marks = list(re.finditer("(USER|ASSISTANT|SYSTEM):\n", text, flags=re.IGNORECASE))
    return [text[m.end():(marks[i + 1].start() if i + 1 < len(marks) else len(text))] for i, m in enumerate(marks)]


def md_files(src):
    return {p.read_text(): f"src/{p.name}" for p in sorted(src.glob("*.md"))}


def appworld(msgs, src):
    tpl = (src / "starting_prompt.md").read_text().lstrip() + "\n\n"
    pieces = split_roles(tpl)
    n = len(pieces)
    slots = {}
    for piece, m in zip(pieces, msgs[:n]):
        s = slots_of(piece, m.get("content") or "")
        if s is None:
            raise ValueError("prompt message does not match the template")
        slots.update(s)
    ev = [{"event": "bridge", "call": "fill", "template": "src/starting_prompt.md", "slots": slots}]
    ev += [{"event": "prompt", "from": "src/starting_prompt.md", "message": m} for m in msgs[:n]]
    md, call = md_files(src), 0
    for m in msgs[n:]:
        c = m.get("content") or ""
        if m["role"] == "assistant":
            call += 1
            ev.append({"event": "model", "call": call, "message": m})
            code = re.search(r"```python\n(.*?)```", c, flags=re.DOTALL)
            ev.append({"event": "bridge", "call": "execute", "code": code.group(1).strip() if code else ""})
        elif m["role"] == "user" and c.startswith("Output:\n"):
            ev.append({"event": "env", "message": m})
        elif c in md:
            ev.append({"event": "harness", "from": md[c], "message": m})
        else:
            ev.append({"event": "harness", "message": m})
    return ev


def alfworld(msgs, src):
    md = md_files(src)
    ev = []
    sysm = msgs[0]
    ev.append({"event": "prompt", "from": "src/starting_prompt.md", "message": sysm})
    ev.append({"event": "bridge", "call": "reset"})
    ev.append({"event": "env", "message": msgs[1]})
    call = 0
    for m in msgs[2:]:
        c = m.get("content") or ""
        if m["role"] == "assistant":
            call += 1
            ev.append({"event": "model", "call": call, "message": m})
        elif m["role"] == "tool":
            prev = next(e for e in reversed(ev) if e["event"] == "model")["message"]
            tc = next((t for t in prev.get("tool_calls") or [] if t.get("id") == m.get("tool_call_id")), None)
            try:
                action = list(json.loads(tc["function"]["arguments"]).values())[0]
            except Exception:  # noqa: BLE001
                action = None
            ev.append({"event": "bridge", "call": "step", "action": action})
            ev.append({"event": "env", "message": m})
        elif c in md:
            ev.append({"event": "harness", "from": md[c], "message": m})
        else:
            ev.append({"event": "harness", "message": m})
    return ev


README_LOGS = {
    "old": "  - `run_N.jsonl` — one episode's conversation, one message per line, as sent to and received from the model.",
    "new": ("  - `run_N.jsonl` — one episode as a stream of events, one per line. `event` says who produced it: "
            "`bridge` — a call to the benchmark (`fill`: the values put into the prompt's slots; `reset`, `step`, "
            "`execute`: what was sent to the environment; `end`: how the episode ended — `finished`, `step limit`, "
            "`error` with `detail`); `prompt` — a message the harness built from "
            "`src/starting_prompt.md`; `env` — a message with the benchmark's result, as the model received it; "
            "`model` — the model's reply; `harness` — other messages from the harness (`from`: its file in `src/`). "
            "The `message` fields in order are the conversation as the model saw it."),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bench", choices=["alfworld", "appworld"], required=True)
    ap.add_argument("--view", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    view, out = Path(a.view), Path(a.out)
    assert not out.exists(), out
    (out / "logs").mkdir(parents=True)
    shutil.copytree(view / "src", out / "src", ignore=shutil.ignore_patterns("__pycache__"))
    readme = (view / "README.md").read_text()
    assert README_LOGS["old"] in readme
    (out / "README.md").write_text(readme.replace(README_LOGS["old"], README_LOGS["new"]))
    shutil.copy(view / "logs" / "results.jsonl", out / "logs" / "results.jsonl")
    conv = appworld if a.bench == "appworld" else alfworld
    reasons = {r["run"]: r["reason"] for r in map(json.loads, (view / "logs" / "results.jsonl").read_text().splitlines())}
    for f in sorted((view / "logs").glob("run_*.jsonl")):
        msgs = [json.loads(x) for x in f.read_text().splitlines() if x.strip()]
        ev = conv(msgs, out / "src")
        ev.append({"event": "bridge", "call": "end", **END[reasons[int(f.stem.split("_")[1])]]})
        assert [e["message"] for e in ev if "message" in e] == msgs, f    # разговор не изменился
        (out / "logs" / f.name).write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in ev))
    print(f"{out}: {len(list((out / 'logs').glob('run_*.jsonl')))} runs")


if __name__ == "__main__":
    main()
