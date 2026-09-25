"""SCOPE (SCOPE/scope: optimizer.py, synthesizer.py, strategic_store.py, memory_optimizer.py; сверка —
tests/bridge/test_bridge_scope.py и записи живой модели tests/live/test_scope.py). Агента у SCOPE нет: решатель —
общий (S1), подключён как в examples/basic_usage.py (SC2).

    извлечение  правило на шаг (extract/scope.py): на каждом шаге с инструментом — сразу, посреди попытки; на
                итоговом ответе — после вопроса
    память      у каждой перспективы своя: strategic по доменам, tactical попытки, допуск и предел домена с
                оптимизатором (memory/scope.py)
    показ       strategic при запуске; принятое на шаге правило переписывает системный промпт (show/scope.py)
    вердикт     верный ответ: неверный итог — ошибка шага

scope_bo2 — Best-of-2 с селектором: кандидат основной модели и candidate_models — та же модель при T = 0.7. scope_code — решатель с исполнением python (как агенты апстрима с
инструментами). scope_k2 — две перспективы по статье (efficiency и thoroughness), у каждой своя память, в зачёт
лучшая по метке: это pass@k, в логе помечено."""
from ..env import Sandbox
from ..extract.scope import Rules
from ..learner import Learner, swap
from ..loop import Attempts, best
from ..memory.scope import EFFICIENCY, THOROUGHNESS, Perspectives
from ..show.scope import StrategicRules

scope = Learner("scope", memory=Perspectives(), show=StrategicRules(), extract=Rules())
scope_bo2 = swap(scope, "scope_bo2", extract=Rules(n=2))
scope_code = swap(scope, "scope_code", env=Sandbox())
scope_k2 = swap(scope, "scope_k2", memory=Perspectives((EFFICIENCY, THOROUGHNESS)), attempts=Attempts(2, pick=best))
