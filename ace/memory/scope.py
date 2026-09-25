"""Память SCOPE (SCOPE/scope: optimizer.py, strategic_store.py, memory_optimizer.py; промпты scope_*.j2 дословно).

У каждой перспективы своя память (Book): strategic правила по доменам с rationale и confidence, tactical —
правила текущей попытки, счётчик принятых за прогон. Допуск: confidence >= 0.5 и не больше 20 принятых за
прогон (max_rules_per_task апстрима, per_run: счётчик на агента и между задачами не сбрасывается, optimizer.py:206);
принятое идёт в tactical; strategic при confidence >= 0.85 без дубля по словам (0.85 в апстриме и параметр
оптимизатора, и зашит в strategic_store.py:201; при значении по умолчанию одно и то же — у нас одна константа);
домен по убыванию confidence, сверх 10 правил (cap) оптимизатор (конфликты, поглощение, слияние, до двух проходов)
сжимает до int(0.8 * cap), остаток обрезается до cap. Запросы оптимизатора — как у OpenAIAdapter апстрима: одно
сообщение user частями, без параметров. Оптимизатор и предел (compress) берёт и ace_opt."""
from dataclasses import dataclass

from .. import parse, prompts, render
from ..model import Call, Reader, parts
from ..extract import ATTEMPT, CONFIDENCE, DOMAIN, RATIONALE
from . import Container, Ids, Record

P = {n: prompts.load(f"scope_{n}") for n in ("analyze", "merge", "subsumed", "conflict")}

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


def rule_optimizer(passes=OPTIMIZER_PASSES):
    """-> optimize(model, rules, target): анализ, затем конфликты, поглощение, слияние, до passes проходов;
    номера правил стабильны между проходами. Модель отвечает текстом, разбор — parse.scope_* (как у апстрима)."""
    def llm(model, name, fields, read):
        return model.ask(Call(parts(P[name].fill(fields)), {}, Reader(text=read))).output

    def resolve(model, rules, pairs):
        by_id, done, fixed = {x["id"]: x for x in rules}, set(), {}
        for pair in pairs:
            if len(pair) < 2 or pair[0] not in by_id or pair[1] not in by_id or pair[0] in done or pair[1] in done:
                continue
            a, b = by_id[pair[0]], by_id[pair[1]]
            r = llm(model, "conflict", dict(idx1=a["id"], rule1_text=a["rule"], rule1_rationale=a["rationale"],
                                            idx2=b["id"], rule2_text=b["rule"], rule2_rationale=b["rationale"]), parse.scope_rule)
            if r:
                done |= {a["id"], b["id"]}
                fixed[a["id"]] = dict(rule=r[0], rationale=r[1], id=a["id"],
                                      confidence=max(a.get("confidence", RULE_CONFIDENCE), b.get("confidence", RULE_CONFIDENCE)))
        return [fixed.get(x["id"], x) for x in rules if x["id"] not in done or x["id"] in fixed]

    def prune_subsumed(model, rules, pairs):
        by_id, gone = {x["id"]: x for x in rules}, set()
        for pair in pairs:
            if len(pair) >= 2 and pair[0] in by_id and pair[1] in by_id:
                if llm(model, "subsumed", dict(general_rule=by_id[pair[0]]["rule"], specific_rule=by_id[pair[1]]["rule"]),
                       parse.scope_subsumed):
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
            # номера в промпте — из группы по порядку, как в апстриме (_merge_rules: indices[i]), даже если
            # какого-то номера среди правил нет
            numbered = [dict(x, id=i) for i, x in zip(group, parts)]
            r = llm(model, "merge", dict(rules_text=render.rule_group(numbered)), parse.scope_rule)
            if r:
                out.append(dict(rule=r[0], rationale=r[1], id=parts[0]["id"],
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
            # с одним правилом апстрим модель не зовёт
            a = (llm(model, "analyze", dict(num_rules=len(rules), rules_text=render.rule_list(rules)), parse.scope_analysis)
                 if len(rules) > 1 else parse.scope_analysis(""))
            if not (a["conflicts"] or a["subsumption"] or a["consolidation"]):
                break
            rules = resolve(model, rules, a["conflicts"])
            rules = prune_subsumed(model, rules, a["subsumption"])
            rules = consolidate(model, rules, a["consolidation"])
        return rules
    return optimize


def compress(model, records, optimizer, target, cap, new):
    """Записи сверх cap сжимаются оптимизатором до target, остаток обрезается до cap. Нетронутая запись
    остаётся собой (id и статистика); исправленное и слитое — новые записи new(правило). Сбой оптимизатора
    (ответ не той формы) — только усечение, как в _optimize_domain_rules апстрима."""
    if len(records) <= cap:
        return records
    rules = [dict(rule=r.text, rationale=getattr(r, "rationale", ""), confidence=getattr(r, "confidence", RULE_CONFIDENCE),
                  record=r) for r in records]
    try:
        rules = optimizer(model, rules, target)
    except Exception:           # апстрим ловит любое исключение оптимизатора
        pass
    return [x["record"] if "record" in x else new(x) for x in rules][:cap]


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

    def __init__(self, name=THOROUGHNESS, optimizer=None, cap=CAP, per_run=PER_RUN):
        self.name, self.optimizer, self.cap, self.per_run = name, optimizer or rule_optimizer(), cap, per_run
        self.target = int(cap * 0.8)    # target_count апстрима
        self.ids, self.domains, self.tactical, self.accepted = Ids(), {}, [], 0

    def records(self):
        return [r for rules in self.domains.values() for r in rules]

    def begin(self, k=0):
        """Новая попытка: tactical прошлой уходят — это срок жизни, а не правка."""
        self.tactical = []

    def learn(self, ex, extractions):
        for x in extractions:
            for text, confidence, domain, rationale in zip(x.lessons, x.extras[CONFIDENCE], x.extras[DOMAIN], x.extras[RATIONALE]):
                self.admit(ex, text, confidence, domain, rationale)

    def admit(self, ex, text, confidence, domain, rationale):
        """_should_accept_update и add_strategic_rule; domain None — правило тактическое."""
        if self.accepted >= self.per_run or confidence < ACCEPT:
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
        self.domains[domain] = compress(ex.model, rules, self.optimizer, self.target, self.cap, new)

    def dump(self, suffix=""):
        """tactical, затем strategic по доменам; suffix — перспектива в имени вида, когда их несколько."""
        return ([dict(kind="tactical" + suffix, **r.dump()) for r in self.tactical] +
                [dict(kind="strategic" + suffix, **r.dump()) for r in self.records()])


class Perspectives(Container):
    """Своя память у каждой перспективы; попытка k работает с памятью перспективы k. Урок идёт в память
    перспективы попытки, на которой он извлечён (attempt)."""
    requires = Book.requires | {ATTEMPT}

    def __init__(self, names=(THOROUGHNESS,), **book):
        self.books = [Book(n, **book) for n in names]

    def book(self, k):
        return self.books[k % len(self.books)]

    def begin(self, k):
        self.book(k).begin()

    def learn(self, ex, extractions):
        for x in extractions:
            for text, confidence, domain, rationale, k in zip(x.lessons, x.extras[CONFIDENCE], x.extras[DOMAIN],
                                                              x.extras[RATIONALE], x.extras[ATTEMPT]):
                self.book(k).admit(ex, text, confidence, domain, rationale)

    def records(self):
        return [r for b in self.books for r in b.records()]

    def key(self):
        return tuple(b.key() for b in self.books)

    def dump(self):
        return [row for b in self.books for row in b.dump(f":{b.name}" if len(self.books) > 1 else "")]
