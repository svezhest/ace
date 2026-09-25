r"""Замер ACE апстрима (ace_exact): сколько меток helpful / harmful доходит до счётчиков.

Цепочка: решатель называет пункты -> разбор находит их id -> рефлектор видит эти пункты и ставит метки ->
метки с id из памяти попадают в счётчики. В апстриме id разбирает регулярка core/generator.py:115
\[([a-z]{3,}-\d{5})\] по всему ответу (json_mode по умолчанию выключен), а промпт просит JSON-список
"bullet_ids": ["calc-00001", ...] без скобок — названное списком она не видит (и не видит ph-). У нас решатель
называет пункты строкой USED; id как у апстрима, регулярка взята как есть.

По каждому раунду рефлектора: названные в USED, распознанные нашим разбором (есть в памяти), распознанные
регуляркой апстрима, метки рефлектора и сколько из них дошло до счётчиков (helpful / harmful с id из памяти).
python scripts/ace_labels.py TASK [N]; строки в results/TASKN/labels_ace_exact/labels.json."""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ace import config  # noqa: E402
from ace.extract.ace import Diagnose, named, tag_map  # noqa: E402
from ace.learner import swap  # noqa: E402
from ace.loop import run  # noqa: E402
from ace.methods import METHODS  # noqa: E402
from ace.model import Model  # noqa: E402
from ace.tasks import TASKS  # noqa: E402

UPSTREAM = re.compile(r"\[([a-z]{3,}-\d{5})\]")      # _extract_bullet_ids_regex (core/generator.py:115)
ROWS = []


class Logged(Diagnose):
    def diagnose(self, ex, ep, memory):
        text, found = super().diagnose(ex, ep, memory)
        tags = list(tag_map(found).items())
        ids = named(ep)
        ROWS.append(dict(epoch=ex.epoch, i=ex.i, ok=ep.ok, memory=len(memory), named=ids,
                         ours=[i for i in ids if memory.get(i)],
                         upstream=[i for i in ids if memory.get(i) and i in UPSTREAM.findall(ep.final)],
                         tags=tags, counted=[t for t in tags if t[1] in ("helpful", "harmful") and memory.get(t[0])]))
        return text, found


def share(a, b):
    return f"{a}/{b} = {a / b:.0%}" if b else f"{a}/0"


if __name__ == "__main__":
    task = TASKS[sys.argv[1]]
    n = int(sys.argv[2]) if len(sys.argv) > 2 else config.SIZE
    out = f"{config.RESULTS}/{task.name}{n}/labels_ace_exact"
    base = METHODS["ace_exact"]
    print(run(task, swap(base, "labels_ace_exact", extract=Logged(base.extract.rounds)), Model(), n, out, epochs=config.EPOCHS))
    json.dump(ROWS, open(f"{out}/labels.json", "w"), ensure_ascii=False, indent=1)
    rows = [r for r in ROWS if r["memory"]]         # пока память пуста, называть нечего
    named = sum(len(r["named"]) for r in rows)
    print(f"раундов рефлектора с непустой памятью: {len(rows)}; с названными пунктами: {sum(bool(r['named']) for r in rows)}")
    print(f"названо решателем:            {named}")
    print(f"распознано разбором USED:     {share(sum(len(r['ours']) for r in rows), named)}")
    print(f"распознано регуляркой апстрима: {share(sum(len(r['upstream']) for r in rows), named)}")
    tags = sum(len(r["tags"]) for r in rows)
    print(f"меток рефлектора: {tags}; дошло до счётчиков: {share(sum(len(r['counted']) for r in rows), tags)}")
