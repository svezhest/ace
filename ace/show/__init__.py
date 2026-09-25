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
показ читает у памяти сверх records() (устройство памяти метода): сборка проверяет, что у памяти это есть."""
from .. import embed, fs, prompts, render
from ..loop import Prompt
from ..model import Patch

HEAD = prompts.text("memory_head")
CATALOG = prompts.load("catalog")
CATALOG_ROUNDS = 3          # лишних шагов решателю на чтение записей каталога


class Show:
    random = False
    watches_steps = False
    reads = ()

    def prompt(self, ex, memory, item, k):
        return Prompt()

    def on_step(self, ex, memory, attempt, step):
        return None


class Whole(Show):
    """Все записи памяти (после pick) в системном промпте: строки line через sep или layout(записи, память).
    Пустой показ — empty, если он задан, иначе ничего."""
    def __init__(self, line=render.numbered, sep="\n", layout=None, head=HEAD, before="", after="", empty=None, reads=()):
        self.line, self.sep, self.layout = line, sep, layout
        self.head, self.before, self.after, self.empty = head, before, after, empty
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
        return self.before + body + self.after, recs

    def prompt(self, ex, memory, item, k):
        text, recs = self.text(ex, memory, item)
        return Prompt("\n\n" + self.head + text, shown=[r.id for r in recs]) if text else Prompt()


class Scored:
    """Запись с близостью к запросу: только для показа, в памяти близости нет."""
    def __init__(self, record, score):
        self.record, self.score = record, score

    def __getattr__(self, name):
        return getattr(self.record, name)


def question(item):
    return item["context"]


class TopK(Whole):
    """k ближайших к запросу query(item) по эмбеддингу key(запись) (embed.similarity), от самой близкой; у каждой
    score. При равной близости порядок — как у argsort апстрима DC."""
    def __init__(self, k, key=lambda r: r.text, query=question, **whole):
        super().__init__(**whole)
        self.k, self.key, self.query = k, key, query

    def pick(self, records, item):
        sims = embed.similarity([self.key(r) for r in records], self.query(item))
        return [Scored(records[i], float(sims[i])) for i in sims.argsort()[::-1][:self.k]]


class Catalog(Show):
    """Записи listed(память) строками каталога в промпте, тела по read(path) из skills/ только на чтение."""
    def __init__(self, listed=lambda memory: memory.records(), rounds=CATALOG_ROUNDS, head=HEAD):
        self.listed, self.rounds, self.head = listed, rounds, head

    def prompt(self, ex, memory, item, k):
        entries = self.listed(memory)
        if not entries:
            return Prompt()
        files = fs.FS({"skills": fs.Mount(fs.Catalog(entries), "ro")})
        return Prompt("\n\n" + self.head + CATALOG.fill(listing=fs.listing(files, "skills")), fs.READ_TOOLS, files, self.rounds)


class AfterError(Show):
    """base при запуске; после шага с ошибкой — записи records(память), чей trigger(запись) встречается в тексте
    ошибки (без учёта регистра), сообщением в конец истории. Префикс истории цел."""
    watches_steps = True

    def __init__(self, base, records, trigger, intro=prompts.text("hook_intro"), line=render.dashed):
        self.base, self.records, self.trigger, self.intro, self.line = base, records, trigger, intro, line
        self.random = base.random

    def prompt(self, ex, memory, item, k):
        return self.base.prompt(ex, memory, item, k)

    def on_step(self, ex, memory, attempt, step):
        patch = self.base.on_step(ex, memory, attempt, step)
        if not step.exec_error:
            return patch
        hit = [r for r in self.records(memory) if self.trigger(r).lower() in step.result.lower()]
        if not hit:
            return patch
        mine = Patch(append=self.intro + render.lines(hit, self.line))
        return mine if patch is None else patch.merge(mine)
