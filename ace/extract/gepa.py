"""Извлечение GEPA апстрима — рефлексия на минибатче (proposer/reflective_mutation/reflective_mutation.py, reflection_lm.py:
StatelessReflectionLM; промпт gepa_reflect.j2 — InstructionProposalSignature.default_prompt_template дословно):
записи DefaultAdapter.make_reflective_dataset (вход, весь ответ, отзыв ContainsAnswerEvaluator с верным ответом и
additional_context вопроса) по вопросам минибатча, один вызов user-сообщением без параметров, разбор
ProposalAdapter.parse. Ответ оборван или не разобран — нового текста нет (кандидата нет, как у апстрима)."""
from .. import parse, prompts, render
from ..model import Call, Reader, messages
from ..upstream.gepa import current
from . import Extraction, Extractor, scores

REFLECT = prompts.load("gepa_reflect")
GEPA = prompts.macros("gepa_strings")
SIDE_INFO = "<side_info>"


def feedback(episode, group):
    """ContainsAnswerEvaluator: верно — с ответом; неверно — с ответом и additional_context вопроса строками
    «ключ: значение»."""
    target = group.target
    if episode.ok:
        return GEPA.correct(answer=target)
    text = GEPA.incorrect(answer=target)
    context = "\n".join(f"{k}: {v}" for k, v in (group.item or {}).get("additional_context", {}).items())
    if context:
        text += GEPA.context(text=context)
    return text


def record(group):
    """Запись рефлексии по вопросу (DefaultReflectiveRecord): вход, весь ответ, отзыв."""
    episode = group.episodes[group.chosen]
    return {GEPA.inputs(): group.question, GEPA.outputs(): episode.final, GEPA.feedback(): feedback(episode, group)}


class Reflection(Extractor):
    scale = "batch"

    def batch(self, ex, groups, memory):
        samples = render.gepa_samples([record(g) for g in groups])
        # как prompt_renderer: <side_info> заменяется после текста кандидата — и в нём тоже
        prompt = REFLECT.fill(curr_param=current(memory, ex.task), side_info=SIDE_INFO).replace(SIDE_INFO, samples)
        reply = ex.model.ask(Call(messages(prompt), {}, Reader(text=parse.gepa_instruction)))
        # finish_reason length без двух оград — ответ оборван (_is_known_truncated)
        if reply.output is None or (reply.truncated and not parse.gepa_fenced((reply.raw or "").strip())):
            return []
        return [Extraction(groups, [reply.output], [s for g in groups for s in scores(g)])]

    def __call__(self, ex, group, memory):
        return (self.batch(ex, [group], memory) or [None])[0]
