"""ACE (Agentic Context Engineering): вариант стенда и вариант апстрима.

ace — стенд, основа цепочки абляций:
    извлечение  рефлектор: уроки и метки пунктов одной схемой (extract/ace.py: Reflector)
    память      пункты-уроки со счётчиками; куратор отвечает операциями ADD / UPDATE одной схемой; отсев вредных
                (memory/ace.py: Playbook)
    показ       все пункты «[id] текст»
    вердикт     верный ответ
ace_text — рефлексия свободным текстом: меток нет, поэтому и память без счётчиков и отсева (иначе стык не
    соберётся: памяти нужны labels).
ace_rewrite — куратор переписывает всю память, пункт на строку: старые пункты уходят со счётчиками, новые — с нуля.

ace_exact — как в апстриме (ace/ace/ace.py, core/, playbook_utils.py; сверка — tests/bridge/test_bridge_ace.py и
    запись живой модели tests/live/test_ace.py):
    решатель    генератор апстрима: playbook, рефлексия, вопрос и context одним сообщением, ответ — final_answer
                из JSON (show/ace.py: GENERATOR)
    извлечение  диагноз с метками, при неверном ответе до 3 раундов с новой попыткой; использованные пункты —
                регулярка апстрима по ответу генератора (extract/ace.py: Diagnose)
    память      playbook из 7 разделов, пункты только добавляются; куратор (последняя рефлексия, контекст вопроса,
                бюджет токенов, статистика) отвечает текстом, из JSON берутся только ADD (memory/ace.py:
                SectionedPlaybook)
    протокол    online апстрима: начальный тест потока, в зачёт тест окна из 15 вопросов до обучения на нём, после
                куратора ещё попытка новым playbook (в лог)
ace_exact_used — общий решатель стенда (S1) с playbook в системном промпте, использованные пункты он называет
    строкой USED; протокол стенда (в зачёт первая попытка обучения).
ace_exact_dedup — после куратора похожие пункты сливаются моделью (BulletpointAnalyzer; в апстриме выключен)."""
from ..extract.ace import Diagnose, Reflector, named
from ..learner import Learner, swap
from ..memory.ace import DEDUP, Playbook, SectionedPlaybook, curate_rewrite
from ..show.ace import GENERATOR, PLAYBOOK

ace = Learner("ace", memory=Playbook(), extract=Reflector())
ace_text = swap(ace, "ace_text", extract=Reflector(free=True), memory=Playbook(prune=None))
ace_rewrite = swap(ace, "ace_rewrite", memory=Playbook(curate_rewrite))

WINDOW = 15                 # --online_eval_frequency апстрима

ace_exact = Learner("ace_exact", memory=SectionedPlaybook(), show=GENERATOR, extract=Diagnose(), window=WINDOW,
                    recheck=True)
ace_exact_used = swap(ace_exact, "ace_exact_used", show=PLAYBOOK, extract=Diagnose(ids=named), window=0, recheck=False)
ace_exact_dedup = swap(ace_exact, "ace_exact_dedup", memory=SectionedPlaybook(dedup=DEDUP))
