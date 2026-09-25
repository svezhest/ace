"""Показ: что из памяти видит решатель и когда. Память показ не меняет.

    prompt(ex, memory, item, k) -> Prompt           перед попыткой k
    on_step(ex, memory, attempt, step) -> Patch      после шага; None — не вмешиваться

Варианты:
    Whole       весь текст: строки записей (line) или раскладка всей памяти (layout)
    TopK        k ближайших к вопросу по эмбеддингу
    Sample      k записей с возвращением, с вероятностью по весу (weight — у метода)
    Choose      одно случайное число выбирает ветку показа (EvoLib: skills, insights или ничего)
    Synth       модель переписывает показанное под вопрос (DC-RS)
    Catalog     в промпте строки каталога (id и head()), тела — инструментом read, только чтение;
                прочитанное цикл пишет в episode.used
    AfterError  после шага с ошибкой — записи, чей триггер есть в тексте ошибки, сообщением в конец истории
                (Patch(append)); исходы показа и сами хуки — позже, с обёрткой Hooks
Переписать системный промпт посреди попытки (SCOPE) — Patch(system) из on_step метода.

random — показ случаен (выборка): val такой памяти не кэшируется. watches_steps — показу нужны шаги попытки."""
import random

from . import embed, fs, prompts, render
from .loop import Prompt
from .model import Patch

HEAD = prompts.text("memory_head")
CATALOG = prompts.load("catalog")
CATALOG_ROUNDS = 3          # лишних шагов решателю на чтение записей каталога


class Show:
    random = False
    watches_steps = False

    def prompt(self, ex, memory, item, k):
        return Prompt()

    def on_step(self, ex, memory, attempt, step):
        return None


class Whole(Show):
    """Все записи памяти (после pick) в системном промпте: строки line через sep или layout(записи, память).
    Пустой показ — empty, если он задан, иначе ничего."""
    def __init__(self, line=render.numbered, sep="\n", layout=None, head=HEAD, before="", after="", empty=None):
        self.line, self.sep, self.layout = line, sep, layout
        self.head, self.before, self.after, self.empty = head, before, after, empty

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
    """k ближайших к запросу query(item) по эмбеддингу key(запись), от самой близкой; у каждой score."""
    def __init__(self, k, key=lambda r: r.text, query=question, **whole):
        super().__init__(**whole)
        self.k, self.key, self.query = k, key, query

    def pick(self, records, item):
        sims = embed.embed([self.key(r) for r in records]) @ embed.embed([self.query(item)])[0]
        return [Scored(records[i], float(sims[i])) for i in sims.argsort()[::-1][:self.k]]


class Sample(Whole):
    """k записей с возвращением, с вероятностью по weight(запись)."""
    random = True

    def __init__(self, k, weight, **whole):
        super().__init__(**whole)
        self.k, self.weight = k, weight

    def pick(self, records, item):
        return random.choices(records, [self.weight(r) for r in records], k=min(len(records), self.k))


class Choose(Show):
    """branches: (накопленная вероятность, показ). Первая ветка, чей порог выше случайного числа и чей показ
    не пуст; иначе ничего (EvoLib: пустая библиотека skills отдаёт ход insights)."""
    random = True

    def __init__(self, *branches):
        self.branches = branches

    def prompt(self, ex, memory, item, k):
        p = random.random()
        for bound, branch in self.branches:
            if p < bound:
                out = branch.prompt(ex, memory, item, k)
                if out.shown:
                    return out
        return Prompt()


class Synth(Show):
    """Модель переписывает показанное base под вопрос: fields(текст base, память, item) -> поля шаблона,
    parse(ответ) -> текст или None (тогда решатель видит сам base). tokens — доля бюджета генерации."""
    def __init__(self, base, template, fields, parse, tokens=1):
        self.base, self.template, self.fields, self.parse, self.tokens = base, template, fields, parse, tokens

    def prompt(self, ex, memory, item, k):
        text, recs = self.base.text(ex, memory, item)
        out = self.parse(ex.model.one("", self.template.fill(self.fields(text or "", memory, item)),
                                      max_tokens=self.tokens * ex.model.max_tokens).text)
        return self.shown(out if out is not None else text, recs)

    def shown(self, text, recs):
        """Промпт из итогового текста; метод, которому нужен сам текст (DC-RS хранит синтез), переопределяет."""
        return Prompt("\n\n" + self.base.head + text, shown=[r.id for r in recs]) if text else Prompt()


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
        if not step.failed:
            return patch
        hit = [r for r in self.records(memory) if self.trigger(r).lower() in step.result.lower()]
        if not hit:
            return patch
        mine = Patch(append=self.intro + render.lines(hit, self.line))
        return mine if patch is None else patch.merge(mine)
