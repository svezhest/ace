"""Dynamic Cheatsheet (dynamic-cheatsheet: dynamic_cheatsheet/language_model.py, run_benchmark.py). Вердикта и
извлечения нет: память читает сырое (вопрос и весь ответ решателя).

dc (DC-Cu) — мир документов:
    память      один текст целиком; куратор после каждого вопроса пишет новый (memory/dc.py: Cheatsheet)
    показ       весь текст, пустой — "(empty)" (show/dc.py)
dc_code — то же с исполнением кода: в апстриме оно включено по умолчанию (execute_python_code=True), процесс на
    каждый вызов — у нас контейнер на вызов.
dc_rs (DC-RS):
    память      пары (вопрос, весь ответ решателя) и последний синтезированный cheatsheet (memory/dc.py: Pairs)
    показ       top-3 прошлых пары и синтез cheatsheet под вопрос (show/dc.py: SYNTHESIS)
Контроли апстрима: dc_retrieval — пары без синтеза (Dynamic_Retrieval), dc_history — все прошлые пары подряд
(FullHistoryAppending)."""
from .. import verdict
from ..env import Sandbox
from ..extract import Raw
from ..learner import Learner, swap
from ..memory.dc import Cheatsheet, Pairs
from ..show.dc import SHEET, SYNTHESIS, history, retrieval

dc = Learner("dc", memory=Cheatsheet(), show=SHEET, extract=Raw(), verdict=verdict.none)
dc_code = swap(dc, "dc_code", env=Sandbox())

dc_rs = Learner("dc_rs", memory=Pairs(sheet=True), show=SYNTHESIS, extract=Raw(), verdict=verdict.none)
dc_retrieval = Learner("dc_retrieval", memory=Pairs(), show=retrieval, extract=Raw(), verdict=verdict.none)
dc_history = swap(dc_retrieval, "dc_history", show=history)
