"""10.11: виды серии писателя runs/plain_1106 -> runs/typed_1110 — тот же харнесс узла на типизированном интерфейсе
хуков (start/template, hook_types.py). Правки узлов перенесены руками, слово в слово; проверка — editor/rerun.py на
журналах вида: «no changes». Ссылки на строки кода во входах in/NN_v_rr.txt правятся отдельно (docs/LAB-1110.md).

  python3 tools/port_typed_1110.py"""
import shutil
import sys
import tempfile
from pathlib import Path

N = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(N / "nrhsi"), str(N / "tools")]
import make_start  # noqa: E402
import plain  # noqa: E402

H = Path(tempfile.mkdtemp())
make_start.make("alfworld", H / "alf")
make_start.make("appworld", H / "app")
OLD, NEW = N / "runs/plain_1106", N / "runs/typed_1110"

def strip(s):
    return plain.strip(s)[0]

def between(s, a, b):
    return s[s.index(a):s.index(b)]

def view(name, bench, harness, hooks=None, types=None):
    d = NEW / name
    if d.exists():
        shutil.rmtree(d)
    shutil.copytree(OLD / name, d, symlinks=True)
    (d / "src/harness.py").write_text(harness)
    (d / "src/hooks.py").write_text(hooks or strip((H / bench / "hooks.py").read_text()))
    (d / "src/hook_types.py").write_text(types or strip((H / bench / "hook_types.py").read_text()))
    (d / "README.md").write_text(plain.README[bench])

alf = strip((H / "alf/harness.py").read_text())
app = strip((H / "app/harness.py").read_text())
alf_types = strip((H / "alf/hook_types.py").read_text())
app_types = strip((H / "app/hook_types.py").read_text())
alf_hooks = strip((H / "alf/hooks.py").read_text())
app_hooks = strip((H / "app/hooks.py").read_text())

# ---- alf_r1, alf_r4chk: тот же цикл, что на старте
view("alf_r1", "alf", alf)
view("alf_r4chk", "alf", alf)

# ---- alf_n4
o = (OLD / "alf_n4/src/harness.py").read_text()
h = alf[:alf.index("def action_of")]
h += between(o, "def action_of", "def make_ctx")
h += between(o, "def _end_status", "def run").replace(
'''def stalled(history):
    tail = history["last_actions"][-STALL_REPEATS:]
    if len(tail) != STALL_REPEATS:
        return False
    return all(not a.strip() for a in tail)''',
'''def stalled(steps):
    tail = steps[-STALL_REPEATS:]
    if len(tail) != STALL_REPEATS:
        return False
    return all(not s.action.strip() for s in tail)''')
r = alf[alf.index("def run"):]
r = r.replace('''    while not episode.finished:
''', '''    while not episode.finished:
        status = _end_status(episode)
        if status == "completed":
            messages.append(user("The task has been completed successfully. You may stop now."))
            break
        if status == "failed":
            messages.append(user("The task failed. The goal was not reached. You may stop now."))
            break
        if stalled(steps):
            messages.append(user("You are stuck: recent actions have not changed the environment. Stop now."))
            break

''')
r = r.replace('''        reply = llm(messages, tools)
        messages.append(reply)
        action = action_of(reply) or ""
''', '''        hint = call_hook(hooks.on_step_countdown, BeforeModelCall(
            earlier_steps=tuple(steps), current_observation=observation, valid_actions=valid_actions,
            turns_left=turns_left), memory, Hint)
        if hint:
            messages.append(user(hint.message))

        reply = llm(messages, tools)
        messages.append(reply)
        result = action_of(reply)
        action = (result[0] if isinstance(result, tuple) else result) or ""
        why = result[1] if isinstance(result, tuple) and len(result) > 1 else ""
''')
r = r.replace('''        for m in episode.send(reply):''', '''        status = _end_status(episode)
        if why == "missing":
            messages.append(user(prompt("no_tool_call.md")))
            if status == "completed":
                messages.append(user("The task has been completed successfully. You may stop now."))
                break
            continue
        if why == "invalid":
            messages.append(user(prompt("invalid_tool_call.md")))
            continue
        if repeated_empty(reply):
            if status == "completed":
                messages.append(user("The task has been completed successfully. You may stop now."))
                break
            messages.append(user("Your action was empty. Choose a real action from the available actions."))
            continue

        for m in episode.send(reply):''')
r = r.replace('messages.append(user(prompt("no_tool_call.md" if not reply.get("tool_calls") else "invalid_tool_call.md")))',
              'messages.append(user(prompt("invalid_tool_call.md")))')
assert r.count("on_step_countdown") == 1 and r.count("repeated_empty") == 1 and r.count("stalled(steps)") == 1
hk = alf_hooks.replace('''def on_before_action''', '''def on_step_countdown(now: BeforeModelCall, memory: dict) -> Optional[Hint]:
    if now.turns_left <= 5:
        return Hint(f"You have {now.turns_left} step(s) left. Act quickly and finish the task now.")
    return None


def on_before_action''')
view("alf_n4", "alf", h + r, hk)

# ---- app_n2
r = app.replace('''        output = episode.execute(code)
        if output is None:
            break
''', '''        output = episode.execute(code)
        if output is None:
            break
        end = episode.end
        if end and end.get("reason") == "error":
            break
''')
assert r != app
view("app_n2", "app", r)

# ---- app_r1, app_r4
def app_r(name):
    o = (OLD / name / "src/harness.py").read_text()
    h = app[:app.index("def call_hook")]
    mid = between(o, "def text_to_messages", "def call_hook")
    if name == "app_r4":
        mid = mid.replace("def _is_new_step(recent_steps, code, output):", "def _is_new_step(recent_steps, code, output):")
    h += app[app.index("def call_hook"):app.index("def text_to_messages")] + mid
    r = app[app.index("def run"):]
    if name == "app_r4":
        r = r.replace("    steps = []\n", "    steps = []\n    recent_steps = []\n")
    skip = ('''            steps.append(Step(None, None))
''' if name == "app_r4" else "")
    r = r.replace('''        code, text = extract_code(reply.get("content") or "")
        reply["content"] = text + "\\n\\n"
        messages.append(reply)
''', '''        content = reply.get("content") or ""

        if all_python_blocks(content):
            blocks = all_python_blocks(content)
            if len(blocks) > 1:
                extra = "\\n\\n".join(f"- {b.strip()!r}" for b in blocks[1:])
                messages.append(user(f"This reply had more than one ```python block. Only the first is "
                                    f"run. Please split this step. Extra blocks were not run: {extra}."))

        code, text = extract_code(content)
        reply["content"] = text + "\\n\\n"
        messages.append(reply)

        if not code:
            messages.append(user("This reply has no ```python code block to run. Write code before "
                                "asking for the next step."))

        if steps and code == steps[-1].code:
            messages.append(user("You sent the same code as in the previous step. This will fail again. "
                                "Stop repeating it. If you have nothing else to try, call "
                                "apis.supervisor.complete_task to finish the task."))
''' + skip + '''            continue
        if steps and output_text(content) == steps[-1].output:
            messages.append(user("The previous step produced this output again. Stop repeating it. If you "
                                "have nothing else to try, call apis.supervisor.complete_task to finish "
                                "the task."))
''' + skip + '''            continue
''' + ('''
        if not _is_new_step(recent_steps, code, output_text(content)):
            messages.append(user("You are repeating the same step as one of the recent steps, or "
                                "restarting the task from the beginning. Stop repeating it. If you have "
                                "nothing else to try, call apis.supervisor.complete_task to finish the "
                                "task."))
            steps.append(Step(None, None))
            continue
''' if name == "app_r4" else ""))
    r = r.replace('''        steps.append(Step(code, output))
''', '''        steps.append(Step(code, output))
''' + ('''        recent_steps.append((code, output))
        if len(recent_steps) > 10:
            recent_steps.pop(0)
''' if name == "app_r4" else "") + '''
        if episode.finished:
            hint = call_hook(hooks.on_completed, AfterStep(
                step=steps[-1], reply_text=text, messages=copy.deepcopy(messages), earlier_steps=tuple(steps[:-1]),
                steps_left=bridge.STEP_LIMIT - episode.steps, benchmark_end=episode.end), memory, Hint)
            if hint:
                messages.append(user(hint.message))
''')
    r = r.replace("steps_left=bridge.STEP_LIMIT - episode.steps), memory, Hint)",
                  "steps_left=bridge.STEP_LIMIT - episode.steps, benchmark_end=episode.end), memory, Hint)")
    assert r.count("benchmark_end=episode.end") == 2, r.count("benchmark_end=episode.end")
    assert "on_completed" in r and "all_python_blocks(content)" in r
    return h + r

types_r = app_types.replace("from dataclasses import dataclass\n", "from dataclasses import dataclass\nfrom typing import Optional\n")
for cls in ("AfterStep",):
    a = types_r.index(f"class {cls}:")
    b = types_r.index("\n\n\n", a)
    types_r = types_r[:b] + "\n    benchmark_end: Optional[dict]" + types_r[b:]
hooks_r1 = app_hooks + '''

def on_completed(now: AfterStep, memory: dict) -> Optional[Hint]:
    return None
'''
view("app_r1", "app", app_r("app_r1"), hooks_r1, types_r)
types_r4 = types_r.replace("    code: str\n    output: str", "    code: Optional[str]\n    output: Optional[str]")
assert types_r4 != types_r
hooks_r4 = app_hooks + '''

def on_completed(now: AfterStep, memory: dict) -> Optional[Hint]:
    verdict = now.benchmark_end or {}
    reason = verdict.get("reason") if isinstance(verdict, dict) else str(verdict)
    message = f"The task was marked {reason}."
    if reason == "step limit":
        message += (f" You ran out of steps. This usually means the model was repeating the same step "
                    f"or restarting the task over and over. Look at the recent steps in the conversation "
                    f"and, if you are repeating or restarting, call "
                    f"apis.supervisor.complete_task to finish.")
    if reason == "error":
        message += (" The benchmark errored. Look at the recent steps in the conversation for the error, "
                    "and, if the task is not actually done, try again; otherwise call "
                    "apis.supervisor.complete_task to finish.")
    if reason == "fail":
        message += " The task was marked as failed."
    return Hint(message)
'''
view("app_r4", "app", app_r("app_r4"), hooks_r4, types_r4)
if not (NEW / "in").exists():
    shutil.copytree(OLD / "in", NEW / "in")
print("ok")
