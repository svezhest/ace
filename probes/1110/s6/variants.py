"""Шаг 6 тикета 10.11: три варианта постановки писателя — только в развилке, база не меняется.
python3 probes/1110/s6/variants.py BASE_DIR OUT_DIR NN...   (модель не вызывается)
Пишет OUT_DIR/<V>/NN.jsonl (псевдолог с метой варианта, для editor/fork.py) и OUT_DIR/<V>/NN.sub.json
(пары OLD/NEW для editor/roll.py --sub). Варианты: B — хвост первого сообщения блоком, цель прежняя;
A — B + одна цель и «готово»; C — A + бюджет сессии в том же блоке.
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

GOAL_BASE = ("Your goal: change src/ so that the agent fails fewer tasks. Each observation that points to a weakness of the "
             "harness is a candidate for a change. An observation may also be inaccurate, or point to something the harness "
             "cannot change; what it says about src/ you can check by reading src/. The same harness runs on every task the "
             "agent gets, so aim for changes that help on tasks in general. A change may be to a prompt or to the code.")
GOAL_B = ("Your goal: change src/ so that the agent fails fewer tasks. The first message holds one observation and, after it, "
          "what is asked of the change. An observation may also be inaccurate, or point to something the harness cannot "
          "change; what it says about src/ you can check by reading src/. The same harness runs on every task the agent "
          "gets, so aim for changes that help on tasks in general. A change may be to a prompt or to the code.")
GOAL_A = ("Your task: make the change to src/ that the observation in the first message calls for, so that the harness "
          "handles the situation it describes. An observation may also be inaccurate, or point to something the harness "
          "cannot change; what it says about src/ you can check by reading src/. The same harness runs on every task the "
          "agent gets: what you change acts in every run, not only in the runs the observation is about. A change may be "
          "to a prompt or to the code.")
CHECKS_BASE = ("- Checks run by themselves: after each edit that is applied, pyflakes, python3 tests/smoke.py and python3 "
               "tests/rerun.py are run on src/, and their output comes with the edit's answer; this uses no bash calls. Read")
CHECKS_C = ("- After each edit that is applied, pyflakes, python3 tests/smoke.py and python3 tests/rerun.py are run on src/, "
            "and their output comes with the edit's answer. Read")
BUDGET_BASE = ("\n- bash can be called 25 times; after that 3 turns remain without bash: edits are still applied and checked "
               "after each one, and then the session ends.")
BUDGET_C = ("- bash can be called 25 times. Edits and the checks after them use no bash calls. After the 25th bash call 3 "
            "turns remain without bash; edits are still applied and checked in them, and then the session ends.")
REPLAY = "Replayed on your src/ (the model's replies are taken from the log), "


def runs(ns):
    ns = [str(n) for n in ns]
    return ("run " + ns[0]) if len(ns) == 1 else ("runs " + ", ".join(ns[:-1]) + " and " + ns[-1])


def tail(ticket, v):
    r, ks = runs(ticket["runs"]), ticket.get("keep") or []
    where = {"control": f"{REPLAY}the harness code should act differently there, not only the texts the model reads.",
             "prompt": f"{REPLAY}the texts the model reads there should change.",
             "any": f"{REPLAY}it should go differently, through the texts the model reads or through the harness code."
             }[ticket["change_expected"]]
    asked = ("A change to src/ so that the agent fails fewer tasks; this observation is where to start." if v == "B" else
             "A change to src/ after which the harness handles what this observation describes.")
    lines = ["## What is asked", asked, f"- Where it shows: {r}. {where}"]
    if ks:
        k = runs(ks)
        lines.append(f"- What should stay: {k}, which passed. Replayed on your src/, {'it' if len(ks) == 1 else 'they'} "
                     f"should go as in {'its log' if len(ks) == 1 else 'their logs'}.")
        lines.append("- Both replays run after each edit and come with the edit's answer.")
    else:
        lines.append("- The replay runs after each edit and comes with the edit's answer.")
    if v in "AC":
        lines.append(f"- Done: in {r} the harness handles what the observation describes"
                     + (f", and {runs(ks)} {'goes' if len(ks) == 1 else 'go'} as in "
                        f"{'its log' if len(ks) == 1 else 'their logs'}." if ks else "."))
    if v == "C":
        lines.append(BUDGET_C)
    return "\n".join(lines)


def subs(first, ticket, v):
    i = first.index("Change expected")
    out = [[first[i:], tail(ticket, v)], [GOAL_BASE, GOAL_B if v == "B" else GOAL_A]]
    if v == "C":
        out += [[CHECKS_BASE, CHECKS_C], [BUDGET_BASE, ""]]
    return out


def main(base, out, nns):
    system = open(f"{base}/system.txt").read()[:-1]
    for v in "BAC":
        os.makedirs(f"{out}/{v}", exist_ok=True)
        for nn in nns:
            first = open(f"{base}/first.{nn}.txt").read()
            ticket = json.load(open(f"{ROOT}/docs/tickets_1106k/{nn}.json"))
            s, f = system, first
            pairs = subs(first, ticket, v)
            for old, new in pairs:
                assert (s + f).count(old) == 1, (v, nn, old[:40])
                s, f = s.replace(old, new), f.replace(old, new)
            open(f"{out}/{v}/{nn}.jsonl", "w").write(json.dumps({"type": "meta", "system": s, "first_user": f},
                                                                 ensure_ascii=False) + "\n")
            json.dump(pairs, open(f"{out}/{v}/{nn}.sub.json", "w"), ensure_ascii=False)
            print(v, nn, len(s), len(f))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3:])
