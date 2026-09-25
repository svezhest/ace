"""Dynamic Cheatsheet (dynamic-cheatsheet: dynamic_cheatsheet/language_model.py, run_benchmark.py; сверка —
tests/bridge/test_bridge_dc.py и записи живой модели tests/live/test_dc.py). Вердикта и извлечения нет: память
читает сырое (весь ответ генератора) и то, что показал решатель (вход задачи, cheatsheet: extract.Seen). Решатель у всех — генератор апстрима (solver/dc.py: Generator).

dc (DC-Cu, DynamicCheatsheet_Cumulative) — мир документов:
    память      один текст целиком; куратор после каждого вопроса пишет новый (memory/dc.py: Cheatsheet)
    показ       весь текст в [[CHEATSHEET]], пустой — "(empty)"
    код         не исполняется (апстрим с --execute_python_code)
dc_code — то же с исполнением кода: в апстриме оно включено по умолчанию (python3 на хосте), у нас песочница.
dc_rs (DC-RS, DynamicCheatsheet_RetrievalSynthesis):
    память      пары (вопрос, весь ответ генератора) и последний синтезированный cheatsheet (memory/dc.py: Pairs)
    показ       top-3 прошлых пары и синтез cheatsheet под вопрос
Контроли апстрима: dc_retrieval — пары без синтеза (Dynamic_Retrieval), dc_history — все прошлые пары подряд
(FullHistoryAppending)."""
from .. import verdict
from ..extract import Seen
from ..learner import Learner, swap
from ..memory.dc import Cheatsheet, Pairs
from ..solver.dc import Generator, cumulative, history, retrieval, synthesis

dc = Learner("dc", memory=Cheatsheet(), solver=Generator(cumulative), extract=Seen(), verdict=verdict.none)
dc_code = swap(dc, "dc_code", solver=Generator(cumulative, code=True))

dc_rs = Learner("dc_rs", memory=Pairs(sheet=True), solver=Generator(synthesis), extract=Seen(), verdict=verdict.none)
dc_retrieval = Learner("dc_retrieval", memory=Pairs(), solver=Generator(retrieval), extract=Seen(), verdict=verdict.none)
dc_history = swap(dc_retrieval, "dc_history", solver=Generator(history))
