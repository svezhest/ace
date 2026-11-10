"""Шаг 3 тикета 10.11: новые входы из отчётов настоящего ревьювера (узлы alf n4 и app n2 деревьев 1.11).
python3 probes/1110/s3/new_inputs.py   (из корня репозитория; модель не вызывается)
Текст наблюдения и evidence — как написал ревьювер; правятся только ссылки на код (вид typed_1110 без комментариев,
с типами хуков): список замен ниже, каждая обязана встретиться ровно один раз. Пишет runs/typed_1110/in/NN_real.txt
и docs/tickets_1110n/NN.json (тикеты мои — верхняя граница; у входа 14 тикета нет).
"""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
HEAD = "Observation from a study of the agent's failed runs (references to logs/ point to the runs in logs/):\n\n"
DOC = (" The docstring even admits this: \"The plain '3 identical observations' test missed every failed run: the model "
       "kept moving to new rooms and taking different actions, so the observations never repeated three times, yet it "
       "was still stuck on a wrong line of reasoning.\"")
NEW = {
    # NN: (дерево, сессия, № отчёта, вид, тикет, замены в наблюдении, замены в evidence, выброшенные пункты evidence)
    "10": ("tree_alf_1101", "n4_0", 1, {"change_expected": "control", "runs": [32], "keep": [1]},
           [(DOC, ""), ("(lines 113-124)", "(lines 64-68)")],
           [("src/harness.py:113-124", "src/harness.py:64-68"), ("src/harness.py:128-137", "src/harness.py:82-84")], []),
    "11": ("tree_alf_1101", "n4_0", 2, {"change_expected": "control", "runs": [29], "keep": [1]},
           [("(harness.py:191-198)", "(harness.py:136-142)"), ("(lines 191-201)", "(lines 136-145)")],
           [("src/harness.py:191-201", "src/harness.py:136-145"), ("src/bridge.py:20-30", "src/bridge.py:26-43")], []),
    "12": ("tree_app_1101", "n2_0", 2, {"change_expected": "any", "runs": [5]},
           [],
           [("src/bridge.py:21-22", "src/bridge.py:46-51"), ("src/harness.py:98-101", "src/harness.py:73-76")], []),
    "13": ("tree_app_1101", "n2_0", 3, {"change_expected": "any", "runs": [8]},
           [],
           [("src/bridge.py:27 STEP_LIMIT", "src/bridge.py:4 STEP_LIMIT"),
            ("src/harness.py:98-110 loop runs episode.execute(action) and continues even when obs is an error",
             "src/harness.py:73-92 loop runs episode.execute(code) and continues even when the output is an error")], []),
    "14": ("tree_app_1101", "n2_2", 6, None,   # наблюдение о том, чего харнесс изменить не может: тикета нет
           [], [],
           ["src/bridge.py: Success is checked by the benchmark after the episode; the agent never sees anything about it."]),
}


def main():
    for nn, (tree, tag, i, ticket, subs_o, subs_e, drop) in NEW.items():
        t = json.load(open(f"{ROOT}/runs/{tree}/tree.json"))
        sess = next(s for n in t["nodes"].values() for s in n.get("sessions") or [] if s["tag"] == tag)
        r = sess["reports"][i]
        obs = r["observation"]
        ev = r.get("evidence_raw") if isinstance(r.get("evidence_raw"), list) else (r.get("evidence") or [])
        ev = [str(x) for x in ev]
        for x in drop:
            assert ev.count(x) == 1, (nn, x)
            ev.remove(x)
        for old, new in subs_o:
            assert obs.count(old) == 1, (nn, old)
            obs = obs.replace(old, new)
        for old, new in subs_e:
            assert sum(old in x for x in ev) == 1, (nn, old)
            ev = [x.replace(old, new) for x in ev]
        text = f"{HEAD}## Observation ({r['kind']})\n{obs}\nEvidence:\n" + "\n".join(f"- {x}" for x in ev) + "\n"
        open(f"{ROOT}/runs/typed_1110/in/{nn}_real.txt", "w").write(text)
        if ticket:
            json.dump(ticket, open(f"{ROOT}/docs/tickets_1110n/{nn}.json", "w"))
        print(nn, tree, tag, i, len(text), ticket)


main()
