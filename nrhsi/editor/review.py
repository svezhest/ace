"""Оценщик правки на finish писателя (автор 13.11): вместо проверок после правки (smoke, rerun, тикет) писатель получает
вердикт оценщика. Две части, каждая своим вызовом (EV14): логика — подача EV6a (блоки задетых прогонов, промпт `runs`),
перепрогон после промпта; промпт — всё, что модель получает до шага 1, до и после правки (`prompt_edit`).
Ok — обе части Ok или пропущены; иначе писатель получает ответ оценщика как есть."""
import json
import os
import re
import sys
import time

from . import cfg as C

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "probes", "1112"))
import ev_input as EI  # noqa: E402
import ev_judge as EJ  # noqa: E402

STAND = "plain27"        # оценщик: 27B без рассуждения, T=0 (EV13, EV14)
FULL = os.path.join(ROOT, "runs", "full_1112")        # полные виды: все прогоны (src тот же, что у видов писателя)
WORK = os.path.join(ROOT, "runs", "evw_1113", "chk")  # копии полных видов с tests/runs.py — для шагов прогонов
ROUNDS = 6               # предохранитель: после стольких вердиктов finish завершает как есть (писателю не печатается)


def _obs(path):
    t = open(path).read()
    return re.sub(r"^Observation from a study of the agent's failed runs[^\n]*\n+", "", t)


def review(run):
    """-> (ok, текст для писателя, запись для лога)."""
    view = os.path.basename(C.VIEWS[C.BENCH])
    full, work, obs = os.path.join(FULL, view), os.path.join(WORK, view), _obs(C.REVIEW_OBS)
    final = EI.ES.read_src(os.path.join(run.root, "src"))
    prof = json.load(open(os.path.join(ROOT, "stands", STAND + ".json")))
    tag = f"{os.path.basename(run.root)}_{run.st['tool_calls']}"
    parts = [("code", EI.build_from([(0, final)], full, C.BENCH, obs, work, tag, blocks=True, logic_only=True), "runs"),
             ("prompt", EI.build_prompt_from(final, full, C.BENCH, obs), "prompt_edit")]
    rec, bad = {"type": "review", "call": run.st["tool_calls"], "stand": STAND, "parts": []}, []
    for name, user, prompt in parts:
        if not user:
            rec["parts"].append({"part": name, "verdict": "skip"})
            continue
        t0 = time.time()
        r = EJ.call(prof, EI.PROMPTS[prompt], user, 1)
        content = r["choices"][0]["message"].get("content") or ""
        v = EJ.parse(content)[0]
        rec["parts"].append({"part": name, "verdict": v, "sec": round(time.time() - t0, 1), "chars_in": len(user),
                             "content": content, "usage": r.get("usage")})
        if v != "Ok":
            bad.append((name, content))
    if not bad:
        return True, "Finished.", rec
    what = {"code": "the change to the code of the harness, with the recorded runs replayed on it",
            "prompt": "the change to what the model gets before its first step (the prompt)"}
    text = ["Not finished yet. A reviewer checked your change against the observation. It does not accept it yet."]
    for name, content in bad:
        text.append(f"The reviewer's answer on {what[name]}:\n{content.strip()}")
    ok_parts = [p["part"] for p in rec["parts"] if p["verdict"] == "Ok"]
    if ok_parts:
        text.append("The reviewer accepted " + " and ".join(what[p] for p in ok_parts) + ".")
    text.append("Change src/ with edit where the reviewer points, then call finish again.")
    return False, "\n\n".join(text), rec
