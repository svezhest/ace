"""Извлечение SCOPE (SCOPE/scope: synthesizer.py, optimizer.py; промпты scope_*.j2 дословно): правило на шаг.

Шаг — вызов инструмента (посреди попытки) или итоговый ответ (после попытки). Правило:
    propose     кандидат по ошибке шага (scope_error) или по качеству (промпт перспективы: thoroughness,
                efficiency); n > 1 — Best-of-N: n кандидатов при BEST_OF_TEMPERATURE и селектор (в апстриме
                кандидаты от разных моделей). Пустой кандидат и «no improvement needed» без ошибки отбрасываются.
    classify    классификатор: дубль — урока нет; уточнённая confidence; домен strategic-правила
Добавки: confidence, domain (None — правило тактическое), rationale.

Что правило видит о памяти, берёт у памяти перспективы попытки (book): её имя (промпт качества),
tactical правила (applied_rules и текущий системный промпт) и текст strategic для классификатора.
Ответы по схеме — структурированный вывод; значения по умолчанию и приведения — как у разбора апстрима
(DEVIATIONS SC1)."""
from pydantic import BaseModel

from .. import prompts, render
from . import CONFIDENCE, DOMAIN, RATIONALE, Extraction, Extractor

P = {n: prompts.load(f"scope_{n}") for n in ("error", "efficiency", "thoroughness", "selector", "classify")}
INTRO = prompts.text("scope_strategic_intro")
GUIDELINE = prompts.text("scope_guideline")

DOMAINS = ["tool_usage", "data_validation", "error_handling", "efficiency", "analysis_methodology", "safety", "general"]
GENERAL = "general"
LEVEL = {"low": 0.3, "medium": 0.6, "high": 0.9}    # метка кандидата -> начальная confidence
DEFAULT_CONFIDENCE = 0.5    # метка не из списка
BEST_OF_TEMPERATURE = 0.7
NO_IMPROVEMENT = ("", "no improvement needed", "none")


class Proposal(BaseModel):
    update_text: str = ""
    rationale: str = ""
    confidence: str | int | float = "medium"   # метка low / medium / high или число, как у апстрима

    def initial(self):
        """Начальная confidence: метка по LEVEL (чужая — DEFAULT_CONFIDENCE), число как есть."""
        c = self.confidence
        return LEVEL.get(c.lower(), DEFAULT_CONFIDENCE) if isinstance(c, str) else float(c)


class Selection(BaseModel):
    selected_index: int = 0


class Classification(BaseModel):
    is_duplicate: bool = False
    scope: str = "tactical"
    confidence: float | None = None
    domain: str = GENERAL


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


def guidelines(book):
    """Правила попытки в конце системного промпта: «## Learned Guideline:» на каждое."""
    return render.lines(book.tactical, render.prefixed(GUIDELINE), "\n\n")


def current_system(system, book):
    """Системный промпт решателя сейчас: как при запуске попытки и tactical правила, принятые в ней."""
    return system + "\n\n" + guidelines(book) if book.tactical else system


def agent_context(ex, attempt, book):
    """Агент глазами SCOPE: роль задачи, вопрос и текущий системный промпт."""
    return dict(agent_name=f"{ex.task.name}_agent", agent_role=ex.task.system, task=attempt.question,
                current_system_prompt=current_system(attempt.system, book))


def meaningful(c):
    return c.update_text.strip().lower() not in NO_IMPROVEMENT


def strategic_text(book):
    """get_strategic_rules_text апстрима; пусто без правил."""
    return render.strategic(INTRO, render.domains(book.domains.items()) if book.records() else "")


class Rules(Extractor):
    gives = frozenset({CONFIDENCE, DOMAIN, RATIONALE})

    def __init__(self, n=1):
        self.n = n

    def propose(self, ex, attempt, book, summary, error):
        """Кандидат правила или None. attempt — идущая попытка или эпизод: вопрос и промпт."""
        fields = dict(agent_context(ex, attempt, book), last_step_summary=summary,
                      applied_rules=render.rules([r.text for r in book.tactical]))
        if error:
            fields.update(error_type=error[0], error_message=error[1])
        prompt = (P["error"] if error else P[book.name]).fill(fields)
        one = lambda t: ex.model.run("", prompt, output=Proposal, temperature=t).output
        if self.n == 1:
            c = one(0)
            if c and not error:         # на качестве апстрим отдаёт текст правила без пробелов по краям
                c.update_text = c.update_text.strip()
            return c if c and c.update_text and (error or meaningful(c)) else None
        cands = [c for c in (one(BEST_OF_TEMPERATURE) for _ in range(self.n)) if c and (error or meaningful(c))]
        if len(cands) < 2:
            best = cands[0] if cands else None
        else:
            s = ex.model.run("", P["selector"].fill(agent_context(ex, attempt, book), issue_type="error" if error else "quality",
                                                    issue_details=render.issue(summary, error),
                                                    candidates=render.candidates(cands)), output=Selection).output
            i = s.selected_index if s else 0
            best = cands[i] if 0 <= i < len(cands) else cands[0]
        return best if best and best.update_text else None

    def classify(self, ex, proposal, book, group=None):
        """Классификатор -> Extraction с одним уроком или None (дубль). Сбой классификатора (и confidence: null,
        на котором падает float() апстрима) — tactical с исходной confidence; strategic с доменом не из списка —
        general."""
        initial = proposal.initial()
        context = prompts.text("scope_rules_context", strategic=strategic_text(book), tactical=[r.text for r in book.tactical])
        c = ex.model.run("", P["classify"].fill(allowed_domains=", ".join(DOMAINS), update_text=proposal.update_text,
                                                rationale=proposal.rationale, initial_confidence=initial,
                                                all_rules_context=context), output=Classification).output
        if c is None or c.confidence is None and "confidence" in c.model_fields_set:
            c = Classification(confidence=initial)
        if c.is_duplicate:
            return None
        confidence = initial if c.confidence is None else c.confidence
        domain = (c.domain if c.domain in DOMAINS else GENERAL) if c.scope == "strategic" else None
        return Extraction(group, [proposal.update_text], [],
                          {CONFIDENCE: [confidence], DOMAIN: [domain], RATIONALE: [proposal.rationale]})

    def step(self, ex, attempt, step, book):
        """Событие шага с инструментом: правило сразу."""
        p = self.propose(ex, attempt, book, *tool_step(step))
        return self.classify(ex, p, book) if p else None

    def answers(self, ex, group, memory):
        """Событие ответа: попытка в зачёт, затем остальные (перспективы); сначала кандидаты всех попыток, потом
        классификация. -> [(номер попытки, Extraction)]."""
        eps = [group.episodes[group.chosen]] + [e for i, e in enumerate(group.episodes) if i != group.chosen]
        proposals = [(e, self.propose(ex, e, memory.book(e.k), *answer_step(e))) for e in eps]
        out = []
        for e, p in proposals:
            x = self.classify(ex, p, memory.book(e.k), group) if p else None
            if x:
                out.append((e.k, x))
        return out

    def __call__(self, ex, group, memory):
        """Одна попытка в группе: её правило."""
        out = self.answers(ex, group, memory)
        return out[0][1] if out else None
