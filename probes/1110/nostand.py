"""Запуск скрипта без живого стенда: сверка стенда с профилем заменена записью {"offline": true}.
Для проигрышей (editor/replay.py) и сессий, где за модель отвечает не стенд.

  python3 probes/1110/nostand.py СКРИПТ АРГУМЕНТЫ...
"""
import os
import runpy
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import stand  # noqa: E402

stand.check = lambda P, roles: {"offline": True}
sys.argv = sys.argv[1:]
sys.path.insert(0, os.path.dirname(os.path.abspath(sys.argv[0])))
runpy.run_path(sys.argv[0], run_name="__main__")
