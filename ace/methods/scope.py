"""SCOPE (SCOPE/scope: optimizer.py, synthesizer.py, strategic_store.py, memory_optimizer.py).
Промпты апстрима дословно в ace/prompts/scope_*.j2.

    память      у каждой перспективы своя (Book): strategic правила по доменам с rationale и confidence,
                tactical — правила текущей попытки, счётчик принятых за прогон. Допуск: confidence >= 0.5 и не
                больше 20 принятых за прогон (max_rules_per_task апстрима: счётчик на агента и между задачами не
                сбрасывается, optimizer.py:206); принятое идёт в tactical; strategic при confidence >= 0.85 без
                дубля по словам (0.85 ещё раз зашито в strategic_store.py:201, у нас одна константа); домен
                по убыванию confidence, сверх 10 правил оптимизатор (конфликты, поглощение, слияние, до двух
                проходов) сжимает до 8, остаток обрезается до 10
    показ       при запуске strategic по доменам; когда на шаге принято правило, Patch переписывает системный
                промпт: исходный + «## Learned Guideline:» на каждое tactical правило (как в апстриме)
    извлечение  правило на шаг (extract/scope.py): на каждом шаге с инструментом — сразу, посреди попытки; на
                итоговом ответе — после вопроса
    вердикт     верный ответ (адаптер repro: неверный итог — ошибка шага)

scope_bo2 — Best-of-2 с селектором. scope_code — решатель с исполнением python (как агенты апстрима с
инструментами). scope_k2 — две перспективы по статье (efficiency и thoroughness), у каждой своя память, в зачёт
лучшая по метке: это pass@k, в логе помечено.
"""
from dataclasses import dataclass

from pydantic import BaseModel

from .. import prompts, render
from ..env import Sandbox
from ..extract import CONFIDENCE, DOMAIN, RATIONALE
from ..extract.scope import INTRO, Rules
from ..learner import Learner, swap
from ..loop import Attempts, best
from ..memory import Container, Ids, Record
from ..model import Patch
from ..show import Show, Whole

P = {n: prompts.load(f"scope_{n}") for n in ("analyze", "merge", "subsumed", "conflict")}
GUIDELINE = prompts.text("scope_guideline")

ACCEPT = 0.5                # auto_accept_threshold "medium"
STRATEGIC = 0.85            # strategic_confidence_threshold
PER_RUN = 20                # max_rules_per_task
CAP, TARGET = 10, 8         # max_strategic_rules_per_domain и int(10 * 0.8)
RULE_CONFIDENCE = 0.85      # confidence записи без своей (пункт ACE в оптимизаторе)
OPTIMIZER_PASSES = 2
DUPLICATE_OVERLAP = 0.7     # доля общих слов, с которой правило — дубль
THOROUGHNESS, EFFICIENCY = "thoroughness", "efficiency"

# оптимизатор правил (MemoryOptimizer); правило — словарь rule, rationale, confidence, id и record, если
# правило пришло из записи памяти и не менялось


class Analysis(BaseModel):
    consolidation: list[list[int]] = []
    subsumption: list[list[int]] = []
    conflicts: list[list[int]] = []


class Rule(BaseModel):
    rule: str
    rationale: str = ""


class Subsumed(BaseModel):
    subsumed: bool = False


def rule_optimizer(passes=OPTIMIZER_PASSES):
    """-> optimize(model, rules, target): анализ, затем конфликты, поглощение, слияние, до passes проходов;
    номера правил стабильны между проходами."""
    llm = lambda model, name, fields, output: model.run("", P[name].fill(fields), output=output).output

    def resolve(model, rules, pairs):
        by_id, done, fixed = {x["id"]: x for x in rules}, set(), {}
        for pair in pairs:
            if len(pair) < 2 or pair[0] not in by_id or pair[1] not in by_id or pair[0] in done or pair[1] in done:
                continue
            a, b = by_id[pair[0]], by_id[pair[1]]
            r = llm(model, "conflict", dict(idx1=a["id"], rule1_text=a["rule"], rule1_rationale=a["rationale"],
                                            idx2=b["id"], rule2_text=b["rule"], rule2_rationale=b["rationale"]), Rule)
            if r:
                done |= {a["id"], b["id"]}
                fixed[a["id"]] = dict(rule=r.rule, rationale=r.rationale, id=a["id"],
                                      confidence=max(a.get("confidence", RULE_CONFIDENCE), b.get("confidence", RULE_CONFIDENCE)))
        return [fixed.get(x["id"], x) for x in rules if x["id"] not in done or x["id"] in fixed]

    def prune_subsumed(model, rules, pairs):
        by_id, gone = {x["id"]: x for x in rules}, set()
        for pair in pairs:
            if len(pair) >= 2 and pair[0] in by_id and pair[1] in by_id:
                r = llm(model, "subsumed", dict(general_rule=by_id[pair[0]]["rule"], specific_rule=by_id[pair[1]]["rule"]), Subsumed)
                if r and r.subsumed:
                    gone.add(pair[1])
        return [x for x in rules if x["id"] not in gone]

    def consolidate(model, rules, groups):
        by_id = {x["id"]: x for x in rules}
        merged = {i for g in groups for i in g}
        out = [x for x in rules if x["id"] not in merged]
        for group in groups:
            parts = [by_id[i] for i in group if i in by_id]
            if len(group) < 2 or not parts:
                out += parts
                continue
            r = llm(model, "merge", dict(rules_text=render.rule_group(parts)), Rule)
            if r:
                out.append(dict(rule=r.rule, rationale=r.rationale, id=parts[0]["id"],
                                confidence=max(x.get("confidence", RULE_CONFIDENCE) for x in parts)))
            else:
                out += parts
        return out

    def optimize(model, rules, target):
        for i, x in enumerate(rules):
            x.setdefault("id", i)
        for _ in range(passes):
            if len(rules) <= target:
                break
            a = llm(model, "analyze", dict(num_rules=len(rules), rules_text=render.rule_list(rules)), Analysis) or Analysis()
            if not (a.conflicts or a.subsumption or a.consolidation):
                break
            rules = resolve(model, rules, a.conflicts)
            rules = prune_subsumed(model, rules, a.subsumption)
            rules = consolidate(model, rules, a.consolidation)
        return rules
    return optimize


def compress(model, records, optimizer, target, cap, new):
    """Записи сверх cap сжимаются оптимизатором до target, остаток обрезается до cap. Нетронутая запись
    остаётся собой (id и статистика); исправленное и слитое — новые записи new(правило)."""
    if len(records) <= cap:
        return records
    rules = [dict(rule=r.text, rationale=getattr(r, "rationale", ""), confidence=getattr(r, "confidence", RULE_CONFIDENCE),
                  record=r) for r in records]
    return [x["record"] if "record" in x else new(x) for x in optimizer(model, rules, target)][:cap]


def duplicate_words(text, texts, overlap=DUPLICATE_OVERLAP):
    """_is_duplicate (strategic_store.py): одна строка — подстрока другой или общих слов больше overlap."""
    new = text.strip().lower()
    for t in texts:
        old = t.strip().lower()
        if new in old or old in new:
            return True
        a, b = set(new.split()), set(old.split())
        if a and b and len(a & b) / max(len(a), len(b)) > overlap:
            return True
    return False

# память


@dataclass(frozen=True, eq=False)
class Strategic(Record):
    """Strategic правило: домен и оценка при рождении."""
    domain: str = ""
    rationale: str = ""
    confidence: float = RULE_CONFIDENCE


class Book(Container):
    """Память одной перспективы. domains — домен -> правила по убыванию confidence (домены в порядке появления,
    как в апстриме); tactical — правила текущей попытки, живут до начала следующей."""
    requires = frozenset({CONFIDENCE, DOMAIN, RATIONALE})

    def __init__(self, name=THOROUGHNESS, optimizer=None):
        self.name, self.optimizer = name, optimizer or rule_optimizer()
        self.ids, self.domains, self.tactical, self.accepted = Ids(), {}, [], 0

    def records(self):
        return [r for rules in self.domains.values() for r in rules]

    def begin(self):
        """Новая попытка: tactical прошлой уходят — это срок жизни, а не правка."""
        self.tactical = []

    def learn(self, ex, extractions):
        for x in extractions:
            for text, confidence, domain, rationale in zip(x.lessons, x.extras[CONFIDENCE], x.extras[DOMAIN], x.extras[RATIONALE]):
                self.admit(ex, text, confidence, domain, rationale)

    def admit(self, ex, text, confidence, domain, rationale):
        """_should_accept_update и add_strategic_rule; domain None — правило тактическое."""
        if self.accepted >= PER_RUN or confidence < ACCEPT:
            return
        self.accepted += 1
        self.tactical.append(Record(self.ids.next(), text))
        if domain is not None and confidence >= STRATEGIC:
            self.promote(ex, text, confidence, domain, rationale)

    def promote(self, ex, text, confidence, domain, rationale):
        rules = self.domains.get(domain, [])
        if duplicate_words(text, [r.text for r in rules]):
            return
        rules = sorted(rules + [Strategic(self.ids.next(), text, domain, rationale, confidence)], key=lambda r: -r.confidence)
        new = lambda x: Strategic(self.ids.next(), x["rule"], domain, x["rationale"], x["confidence"])
        self.domains[domain] = compress(ex.model, rules, self.optimizer, TARGET, CAP, new)

    def dump(self, suffix=""):
        """tactical, затем strategic по доменам; suffix — перспектива в имени вида, когда их несколько."""
        return ([dict(kind="tactical" + suffix, **r.dump()) for r in self.tactical] +
                [dict(kind="strategic" + suffix, **r.dump()) for r in self.records()])


class Perspectives(Container):
    """Своя память у каждой перспективы; попытка k работает с памятью перспективы k."""
    requires = Book.requires

    def __init__(self, names=(THOROUGHNESS,)):
        self.books = [Book(n) for n in names]

    def book(self, k):
        return self.books[k % len(self.books)]

    def records(self):
        return [r for b in self.books for r in b.records()]

    def key(self):
        return tuple(b.key() for b in self.books)

    def dump(self):
        return [row for b in self.books for row in b.dump(f":{b.name}" if len(self.books) > 1 else "")]

# показ


class ByPerspective(Show):
    """Показ base над памятью перспективы попытки."""
    def __init__(self, base):
        self.base = base

    def prompt(self, ex, memory, item, k):
        return self.base.prompt(ex, memory.book(k), item, k)


STRATEGIC_RULES = ByPerspective(Whole(layout=lambda records, book: render.domains(book.domains.items()), before=INTRO, head=""))


def guidelines(rules):
    return render.lines(rules, render.prefixed(GUIDELINE), "\n\n")

# ученик


@dataclass
class Scope(Learner):
    """Учится на шаге с инструментом (правило сразу, со следующего запроса оно в системном промпте) и на
    итоговом ответе (после вопроса, на батче). patch="append" — абляция: новое правило дописывается
    сообщением в конец истории, системный промпт и префикс истории целы."""
    patch: str = "system"

    def prompt(self, ex, item, k, memory=None):
        (memory or self.memory).book(k).begin()
        return super().prompt(ex, item, k, memory)

    def watches_steps(self):
        return True

    def on_step(self, ex, attempt, step):
        if not attempt.training:
            return None
        book = self.memory.book(attempt.k)
        before = len(book.tactical)
        x = self.extract.step(ex, attempt, step, book)
        if x:
            book.learn(ex, [x])
        if len(book.tactical) == before:
            return None
        if self.patch == "append":
            return Patch(append=guidelines(book.tactical[before:]))
        return Patch(system=attempt.system + "\n\n" + guidelines(book.tactical))

    def on_question(self, ex, group):
        self.pending += self.extract.answers(ex, group, self.memory)

    def on_batch(self, ex, groups):
        for k, x in self.pending:
            self.memory.book(k).learn(ex, [x])
        self.pending = []


scope = Scope("scope", memory=Perspectives(), show=STRATEGIC_RULES, extract=Rules())
scope_bo2 = swap(scope, "scope_bo2", extract=Rules(n=2))
scope_code = swap(scope, "scope_code", env=Sandbox())
scope_k2 = swap(scope, "scope_k2", memory=Perspectives((EFFICIENCY, THOROUGHNESS)), attempts=Attempts(2, pick=best))
