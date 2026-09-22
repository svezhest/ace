"""Варианты показа памяти решателю, общие для методов."""
from . import embed


def topk(k):
    """Только k записей, ближайших по эмбеддингу к вопросу. Вопрос кладёт в memory.query хук prepare."""
    def prepare(model, memory, item):
        memory.query = item["context"]

    def inject(memory):
        recs = [r for r in memory.records if r.kind != "episode"]
        picked = [recs[i] for i in embed.top(memory.query, [r.text for r in recs], k)]
        memory.used = [r.id for r in picked]
        return "\n".join(f"[{r.id}] {r.text}" for r in picked)
    return prepare, inject
