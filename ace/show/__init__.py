"""Показ: что из памяти видит решатель и когда. Память показ не меняет. Здесь общие варианты, показ методов —
в show/<метод>.py.

    prompt(ex, memory, item, k) -> Prompt           перед попыткой k
    on_step(ex, memory, attempt, step) -> Patch      после шага; None — не вмешиваться

Варианты:
    Whole       весь текст: строки записей (line) или раскладка всей памяти (layout)
    TopK        k ближайших к вопросу по эмбеддингу
    Catalog     в промпте строки каталога (id и head()), тела — инструментом read, только чтение;
                прочитанное цикл пишет в episode.used
    AfterError  после шага с ошибкой исполнения — записи, чей триггер есть в тексте ошибки, сообщением в конец истории
                (Patch(append)); исходы показа и сами хуки — у обёртки Hooks
Переписать системный промпт посреди попытки (SCOPE) — Patch(system) из on_step показа.

random — показ случаен: val такой памяти не кэшируется. watches_steps — показу нужны шаги попытки. reads — что
показ читает у памяти сверх records() (устройство памяти метода): сборка проверяет, что у памяти это есть. shows —
что показ кладёт в Prompt.seen (у общих показов — ничего)."""
from .. import embed, fs, prompts, render
from ..loop import Prompt, combine
from ..model import Patch

HEAD = prompts.text("memory_head")
CATALOG = prompts.load("catalog")
CATALOG_ROUNDS = 3          # лишних шагов решателю на чтение записей каталога
HOOK_INTRO = prompts.text("hook_intro")


class Show:
    random = False
    watches_steps = False
    reads = ()
    shows = frozenset()         # что показ кладёт в Prompt.seen для извлечения

    def prompt(self, ex, memory, item, k):
        return Prompt()

    def on_step(self, ex, memory, attempt, step):
        return None


class Whole(Show):
    """Все записи памяти (после pick) в системном промпте: строки line через sep или layout(записи, память).
    Пустой показ — empty, если он задан, иначе ничего."""
    def __init__(self, line=render.numbered, sep="\n", layout=None, head=HEAD, after="", empty=None, reads=()):
        self.line = line
        self.sep = sep
        self.layout = layout
        self.head = head
        self.after = after      # приписка после записей
        self.empty = empty
        self.reads = reads      # что раскладка layout читает у памяти

    def pick(self, records, item):
        return records

    def text(self, ex, memory, item):
        """-> (текст без заголовка или None, показанные записи)."""
        recs = memory.records()
        if recs:
            recs = self.pick(recs, item)
        if not recs:
            return self.empty or None, []
        body = self.layout(recs, memory) if self.layout else render.lines(recs, self.line, self.sep)
        return body + self.after, recs

    def prompt(self, ex, memory, item, k):
        text, recs = self.text(ex, memory, item)
        if not text:
            return Prompt()
        return Prompt("\n\n" + self.head + text, shown=[r.id for r in recs])


class Scored:
    """Запись с близостью к запросу — только для показа, в памяти близости нет. Поля записи (id, text, question у
    пар DC) читаются насквозь: показ и раскладка работают со Scored как с записью; score — близость."""
    def __init__(self, record, score):
        self.record = record
        self.score = score

    def __getattr__(self, name):
        return getattr(self.record, name)


def text_of(record):
    return record.text


class TopK(Whole):
    """k ближайших к вопросу по эмбеддингу key(запись) (embed.similarity), от самой близкой; у каждой score. При
    равной близости порядок — как у argsort апстрима DC."""
    def __init__(self, k, key=text_of, **whole):
        super().__init__(**whole)
        self.k = k
        self.key = key

    def pick(self, records, item):
        sims = embed.similarity([self.key(r) for r in records], item["question"])
        return [Scored(records[i], float(sims[i])) for i in sims.argsort()[::-1][:self.k]]


class Catalog(Show):
    """Все записи строками каталога в промпте, тела по read(path) из skills/ только на чтение."""
    def prompt(self, ex, memory, item, k):
        entries = memory.records()
        if not entries:
            return Prompt()
        files = fs.FS({"skills": fs.Mount(fs.Records(entries), "ro")})
        text = "\n\n" + HEAD + CATALOG.fill(listing=fs.listing(files, "skills"))
        return Prompt(text, tools=fs.READ_TOOLS, deps=files, rounds=CATALOG_ROUNDS)


def trigger_of(record):
    return record.trigger


class AfterError(Show):
    """base при запуске; после шага с ошибкой исполнения — записи памяти, чей trigger(запись) встречается в тексте
    ошибки (без учёта регистра), сообщением в конец истории. Префикс истории цел."""
    watches_steps = True

    def __init__(self, base, trigger=trigger_of, intro=HOOK_INTRO, line=render.dashed):
        self.base = base
        self.trigger = trigger
        self.intro = intro
        self.line = line
        self.random = base.random

    def prompt(self, ex, memory, item, k):
        return self.base.prompt(ex, memory, item, k)

    def on_step(self, ex, memory, attempt, step):
        patch = self.base.on_step(ex, memory, attempt, step)
        if not step.exec_error:
            return patch
        error = step.result.lower()
        hit = [r for r in memory.records() if self.trigger(r).lower() in error]
        if not hit:
            return patch
        return combine(patch, Patch(append=self.intro + render.lines(hit, self.line)))
