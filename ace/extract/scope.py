"""Извлечение SCOPE (SCOPE/scope: synthesizer.py, optimizer.py; промпты scope_*.j2 дословно): правило на шаг.

Шаг — вызов инструмента (посреди попытки) или итоговый ответ (после попытки). Правило:
    propose     кандидат по ошибке шага (scope_error) или по качеству (промпт перспективы: thoroughness,
                efficiency); n > 1 — Best-of-N: кандидат основной модели и n - 1 от candidate_models (у нас та же
                модель при BEST_OF_TEMPERATURE), затем селектор. Пустой кандидат и «no improvement needed» без
                ошибки отбрасываются.
    classify    классификатор: дубль — урока нет; уточнённая confidence; домен strategic-правила
Добавки: confidence, domain (None — правило тактическое), rationale, attempt (память перспективы попытки).

Что правило видит о памяти, берёт у памяти перспективы попытки (book): её имя (промпт качества),
tactical правила (applied_rules и текущий системный промпт) и текст strategic для классификатора.
Запросы — как у OpenAIAdapter апстрима (create_openai_model): одно сообщение user частями, без параметров. Модель
отвечает текстом, разбор — функции апстрима в parse.py (scope_*), с его откатами."""
from dataclasses import dataclass
from functools import partial

from .. import parse, prompts, render
from ..model import Call, Reader, parts
from ..upstream.scope import current_system, strategic_text
from . import ATTEMPT, CONFIDENCE, DOMAIN, RATIONALE, Extraction, Extractor

ERROR = prompts.load("scope_error")
QUALITY = {"thoroughness": prompts.load("scope_thoroughness"), "efficiency": prompts.load("scope_efficiency")}
SELECTOR = prompts.load("scope_selector")
CLASSIFY = prompts.load("scope_classify")
DOMAINS = prompts.text("scope_domains").split()
STAND = prompts.macros("stand")
LEVEL = {"low": 0.3, "medium": 0.6, "high": 0.9}    # метка кандидата -> начальная confidence
DEFAULT_CONFIDENCE = 0.5    # метка не из списка
BEST_OF_TEMPERATURE = 0.7


@dataclass
class Proposal:
    """Кандидат правила (Guideline апстрима)."""
    update_text: str = ""
    rationale: str = ""
    confidence: object = "medium"       # метка low / medium / high или число, как пришло от модели

    def initial(self):
        """Начальная confidence: метка по LEVEL (чужая — DEFAULT_CONFIDENCE), число как есть, прочее (null) —
        DEFAULT_CONFIDENCE."""
        c = self.confidence
        if isinstance(c, str):
            return LEVEL.get(c.lower(), DEFAULT_CONFIDENCE)
        if isinstance(c, (int, float)) and not isinstance(c, bool):
            return float(c)
        return DEFAULT_CONFIDENCE


def tool_step(step):
    """Шаг с инструментом -> сводка и ошибка (тип, сообщение) или None."""
    summary = render.step_summary(tools=render.tool_call(step.tool, step.args), observations=step.result)
    error = render.tool_error(step.result) if step.failed else None
    return summary, error


def answer_step(ep):
    """Итоговый шаг -> сводка ответа и ошибка: неверный ответ (с верным, если он есть) или обрыв."""
    error = None
    if ep.ok is False:
        error = render.incorrect_answer(ep.answer, ep.target)
    elif ep.truncated:
        error = render.truncated_answer()
    return render.step_summary(ep.output, observations=render.answer_seen(ep.ok)), error


def agent_context(ex, attempt, book):
    """Агент глазами SCOPE: роль задачи, вопрос и текущий системный промпт."""
    return dict(agent_name=STAND.agent_name(task=ex.task.name), agent_role=ex.task.system, task=attempt.question,
                current_system_prompt=current_system(attempt.system, book))


def meaningful(c):
    return c.update_text.strip().lower() not in parse.NO_IMPROVEMENT


class Rules(Extractor):
    gives = frozenset({CONFIDENCE, DOMAIN, RATIONALE, ATTEMPT})
    steps = True

    def __init__(self, n=1):
        self.n = n

    def propose(self, ex, attempt, book, summary, error):
        """Кандидат правила или None. attempt — идущая попытка или эпизод: вопрос и промпт."""
        fields = dict(agent_context(ex, attempt, book), last_step_summary=summary,
                      applied_rules=render.rules([r.text for r in book.tactical]))
        if error:
            prompt = ERROR.fill(**fields, error_type=error[0], error_message=error[1])
        else:
            prompt = QUALITY[book.name].fill(**fields)
        if self.n == 1:
            best = self.candidate(ex, prompt, {}, quality=not error)
        else:
            best = self.best_of(ex, attempt, book, prompt, summary, error)
        return best if best and best.update_text else None

    def candidate(self, ex, prompt, request, quality):
        """Кандидат синтезатора или None; quality — правило по качеству: пустое и «no improvement needed» — None."""
        read = Reader(text=partial(parse.scope_guideline, quality=quality))
        c = ex.model.ask(Call(parts(prompt), request, read)).output
        return Proposal(**c) if c else None

    def best_of(self, ex, attempt, book, prompt, summary, error):
        """Best-of-N: кандидат основной модели и n - 1 от candidate_models (у нас та же модель при
        BEST_OF_TEMPERATURE), пустые без ошибки отбрасываются, из двух и больше выбирает селектор."""
        requests = [{}] + [{"temperature": BEST_OF_TEMPERATURE}] * (self.n - 1)
        cands = []
        for request in requests:
            c = self.candidate(ex, prompt, request, quality=False)
            if c and (error or meaningful(c)):
                cands.append(c)
        if len(cands) < 2:
            return cands[0] if cands else None
        select = SELECTOR.fill(**agent_context(ex, attempt, book), issue_type="error" if error else "quality",
                               issue_details=render.issue(summary, error), candidates=render.candidates(cands))
        read = Reader(text=partial(parse.scope_selection, n=len(cands)))
        return cands[ex.model.ask(Call(parts(select), {}, read)).output]

    def classify(self, ex, proposal, book, k=0, group=None):
        """Классификатор -> Extraction с одним уроком попытки k или None (дубль); сбой разбора — tactical с исходной
        confidence (parse.scope_classification)."""
        initial = proposal.initial()
        rules = prompts.text("scope_rules_context", strategic=strategic_text(book), tactical=[r.text for r in book.tactical])
        prompt = CLASSIFY.fill(allowed_domains=render.allowed_domains(DOMAINS), update_text=proposal.update_text,
                               rationale=proposal.rationale, initial_confidence=initial, all_rules_context=rules)
        read = Reader(text=partial(parse.scope_classification, initial=initial, domains=DOMAINS))
        c = ex.model.ask(Call(parts(prompt), {}, read)).output
        if c["is_duplicate"]:
            return None
        domain = c["domain"] if c["scope"] == "strategic" else None
        extras = {CONFIDENCE: [c["confidence"]], DOMAIN: [domain], RATIONALE: [proposal.rationale], ATTEMPT: [k]}
        return Extraction(group, [proposal.update_text], [], extras)

    def step(self, ex, attempt, step, memory):
        """Событие шага с инструментом: правило сразу, посреди попытки."""
        book = memory.book(attempt.k)
        proposal = self.propose(ex, attempt, book, *tool_step(step))
        return self.classify(ex, proposal, book, attempt.k) if proposal else None

    def __call__(self, ex, group, memory):
        """Событие ответа: попытка в зачёт, затем остальные (перспективы); сначала кандидаты всех попыток, потом
        классификация. Правила всех попыток — одно извлечение, в порядке попыток."""
        chosen = group.episodes[group.chosen]
        order = [chosen] + [e for e in group.episodes if e is not chosen]
        proposals = [(e, self.propose(ex, e, memory.book(e.k), *answer_step(e))) for e in order]
        lessons = []
        extras = {name: [] for name in self.gives}
        for e, proposal in proposals:
            x = self.classify(ex, proposal, memory.book(e.k), e.k, group) if proposal else None
            if x is None:
                continue
            lessons += x.lessons
            for name in self.gives:
                extras[name] += x.extras[name]
        if not lessons:
            return None
        return Extraction(group, lessons, [], extras)
