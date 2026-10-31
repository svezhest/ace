"""Исследователь харнесса на 9B — запуск на стенде. Код — nrhsi/researcher/; сессии — здесь: logs/<имя>.jsonl,
views/<имя>/; вид по умолчанию — alfworld/view_v3.

python fsr.py --view ../alfworld/view_v3 --runs 4,8,12 --policy base --seed 1 --tag s1
python fsr.py --view ../appworld/view_v3 --k 5 --seed 1 --policy final --tag s1

fsr.ИМЯ = имя из модуля-владельца nrhsi.researcher, и чтение, и присваивание (fsr.THINKING = True,
fsr.chat = заглушка) идут туда, откуда его читают функции.
"""
import os
import sys

sys.dont_write_bytecode = True
_HERE = os.path.dirname(os.path.abspath(__file__))
if os.path.dirname(_HERE) not in sys.path:
    sys.path.insert(0, os.path.dirname(_HERE))
from nrhsi import facade as _facade  # noqa: E402
from nrhsi.researcher import cfg as _cfg, policy as _policy  # noqa: E402

_cfg.HERE = _HERE
_cfg.LAYOUT = os.path.join(os.path.dirname(_HERE), "alfworld", "view_v3")
_facade.install(__name__, _policy.PARTS)

if __name__ == "__main__":
    _policy.L.main()
