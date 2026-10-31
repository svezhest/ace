"""Редактор харнесса на 9B — запуск на стенде. Код — nrhsi/editor/; сессии — здесь: logs/, out/, work/;
виды по умолчанию — <бенч>/view_v3, report на входе — из researcher/logs, pyflakes — из editor/lint/.

python editor.py --bench alf --input a7k5ef --arm obs --seed 1 --tag b1_alf_a7k5ef_obs
python editor.py --bench alf --input a7k5ef --arm fix --seed 1 --tag b1_alf_a7k5ef_fix
python editor.py ... --dry      # напечатать промпты и первые сообщения, без модели

editor.ИМЯ = имя из модуля-владельца nrhsi.editor, и чтение, и присваивание (E.BASH_LIMIT = 2,
E.F.chat = заглушка) идут туда, откуда его читают функции.
"""
import os
import sys

sys.dont_write_bytecode = True
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
from nrhsi import facade as _facade  # noqa: E402
from nrhsi import editor as _E  # noqa: E402

F = _E.F
_E.cfg.HERE, _E.cfg.RLOGS, _E.cfg.LINT = _HERE, f"{_ROOT}/researcher/logs", f"{_HERE}/lint"
_E.cfg.VIEWS.update(alf=f"{_ROOT}/alfworld/view_v3", app=f"{_ROOT}/appworld/view_v3")
_facade.install(__name__, _E.PARTS)

if __name__ == "__main__":
    _E.cli.main()
