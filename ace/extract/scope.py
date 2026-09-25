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

from .. import parse, prompts, render
from ..model import Call, Reader, parts
from ..upstream.scope import current_system, strategic_text
from . import ATTEMPT, CONFIDENCE, DOMAIN, RATIONALE, Extraction, Extractor

P = {n: prompts.load(f"scope_{n}") for n in ("error", "efficiency", "thoroughness", "selector", "classify")}

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
        return float(c) if isinstance(c, (int, float)) and not isinstance(c, bool) else DEFAULT_CONFIDENCE


def tool_step(step):
    """Шаг с инструментом -> сводка и ошибка (тип, сообщение) или None."""
    summary = render.step_summary(tools=render.tool_call(step.tool, step.args), observations=step.result)
    return summary, render.tool_error(step.result) if step.failed else None


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
            fields.update(error_type=error[0], error_message=error[1])
        prompt = (P["error"] if error else P[book.name]).fill(**fields)

        def one(extra, quality):
            read = Reader(text=lambda text: parse.scope_guideline(text, quality))
            c = ex.model.ask(Call(parts(prompt), extra, read)).output
            return Proposal(**c) if c else None
        if self.n == 1:
            c = one({}, not error)
            return c if c and c.update_text else None
        models = [{}] + [{"temperature": BEST_OF_TEMPERATURE}] * (self.n - 1)
        cands = [c for c in (one(p, False) for p in models) if c and (error or meaningful(c))]
        if len(cands) < 2:
            best = cands[0] if cands else None
        else:
            select = P["selector"].fill(**agent_context(ex, attempt, book), issue_type="error" if error else "quality",
                                        issue_details=render.issue(summary, error), candidates=render.candidates(cands))
            read = Reader(text=lambda text: parse.scope_selection(text, len(cands)))
            best = cands[ex.model.ask(Call(parts(select), {}, read)).output]
        return best if best and best.update_text else None

    def classify(self, ex, proposal, book, k=0, group=None):
        """Классификатор -> Extraction с одним уроком попытки k или None (дубль); сбой разбора — tactical с исходной
        confidence (parse.scope_classification)."""
        initial = proposal.initial()
        context = prompts.text("scope_rules_context", strategic=strategic_text(book), tactical=[r.text for r in book.tactical])
        prompt = P["classify"].fill(allowed_domains=render.allowed_domains(DOMAINS), update_text=proposal.update_text,
                                    rationale=proposal.rationale, initial_confidence=initial, all_rules_context=context)
        read = Reader(text=lambda text: parse.scope_classification(text, initial, DOMAINS))
        c = ex.model.ask(Call(parts(prompt), {}, read)).output
        if c["is_duplicate"]:
            return None
        domain = c["domain"] if c["scope"] == "strategic" else None
        return Extraction(group, [proposal.update_text], [], {CONFIDENCE: [c["confidence"]], DOMAIN: [domain],
                                                              RATIONALE: [proposal.rationale], ATTEMPT: [k]})

    def step(self, ex, attempt, step, memory):
        """Событие шага с инструментом: правило сразу, посреди попытки."""
        book = memory.book(attempt.k)
        p = self.propose(ex, attempt, book, *tool_step(step))
        return self.classify(ex, p, book, attempt.k) if p else None

    def __call__(self, ex, group, memory):
        """Событие ответа: попытка в зачёт, затем остальные (перспективы); сначала кандидаты всех попыток, потом
        классификация. Правила всех попыток — одно извлечение, в порядке попыток."""
        eps = [group.episodes[group.chosen]] + [e for i, e in enumerate(group.episodes) if i != group.chosen]
        proposals = [(e, self.propose(ex, e, memory.book(e.k), *answer_step(e))) for e in eps]
        xs = [x for x in (self.classify(ex, p, memory.book(e.k), e.k, group) if p else None for e, p in proposals) if x]
        if not xs:
            return None
        return Extraction(group, [t for x in xs for t in x.lessons], [],
                          {name: [v for x in xs for v in x.extras[name]] for name in self.gives})
