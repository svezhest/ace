"""Dynamic Cheatsheet (dynamic-cheatsheet: dynamic_cheatsheet/language_model.py, run_benchmark.py; сверка —
tests/bridge/test_bridge_dc.py и записи живой модели tests/live/test_dc.py). Вердикта и извлечения нет: память
читает сырое (вход задачи и весь ответ генератора). Решатель у всех — генератор апстрима (show/dc.py: Generator).

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
from ..extract import Raw
from ..learner import Learner, swap
from ..memory.dc import Cheatsheet, Pairs
from ..show.dc import Generator, cumulative, history, retrieval, synthesis

dc = Learner("dc", memory=Cheatsheet(), show=Generator(cumulative), extract=Raw(), verdict=verdict.none)
dc_code = swap(dc, "dc_code", show=Generator(cumulative, code=True))

dc_rs = Learner("dc_rs", memory=Pairs(sheet=True), show=Generator(synthesis), extract=Raw(), verdict=verdict.none)
dc_retrieval = Learner("dc_retrieval", memory=Pairs(), show=Generator(retrieval), extract=Raw(), verdict=verdict.none)
dc_history = swap(dc_retrieval, "dc_history", show=Generator(history))
