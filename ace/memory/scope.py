"""Память SCOPE (SCOPE/scope: optimizer.py, strategic_store.py, memory_optimizer.py; промпты scope_*.j2 дословно).

У каждой перспективы своя память (Book): strategic правила по доменам с rationale и confidence, tactical —
правила текущей попытки, счётчик принятых за прогон. Допуск: confidence >= 0.5 и не больше 20 принятых за
прогон (max_rules_per_task апстрима, per_run: счётчик на агента и между задачами не сбрасывается, optimizer.py:206);
принятое идёт в tactical; strategic при confidence >= 0.85 без дубля по словам (0.85 в апстриме и параметр
оптимизатора, и зашит в strategic_store.py:201; при значении по умолчанию одно и то же — у нас одна константа);
домен по убыванию confidence, сверх 10 правил (cap) оптимизатор (конфликты, поглощение, слияние, до двух проходов)
сжимает до int(0.8 * cap), остаток обрезается до cap. Запросы оптимизатора — как у OpenAIAdapter апстрима: одно
сообщение user частями, без параметров. Оптимизатор и предел (compress) берёт и ace_stand_opt."""
from dataclasses import dataclass

from .. import parse, prompts, render
from ..model import Call, Reader, parts
from ..extract import ATTEMPT, CONFIDENCE, DOMAIN, RATIONALE
from . import Container, Ids, Record

ANALYZE = prompts.load("scope_analyze")
MERGE = prompts.load("scope_merge")
SUBSUMED = prompts.load("scope_subsumed")
CONFLICT = prompts.load("scope_conflict")

ACCEPT = 0.5                # auto_accept_threshold "medium"
STRATEGIC = 0.85            # strategic_confidence_threshold
PER_RUN = 20                # max_rules_per_task
CAP = 10                    # max_strategic_rules_per_domain
TARGET_SHARE = 0.8          # оптимизатор сжимает домен до int(0.8 * cap) правил (target_count)
RULE_CONFIDENCE = 0.85      # confidence записи без своей (пункт ACE в оптимизаторе)
OPTIMIZER_PASSES = 2
DUPLICATE_OVERLAP = 0.7     # доля общих слов, с которой правило — дубль
THOROUGHNESS = "thoroughness"
EFFICIENCY = "efficiency"

# оптимизатор правил (MemoryOptimizer); правило — словарь rule, rationale, confidence, id и record, если
# правило пришло из записи памяти и не менялось. Модель отвечает текстом, разбор — parse.scope_* (как у апстрима)


def ask_optimizer(model, template, read, **fields):
    return model.ask(Call(parts(template.fill(**fields)), {}, Reader(text=read))).output


def confidence(rule):
    return rule.get("confidence", RULE_CONFIDENCE)


def resolve(model, rules, pairs):
    """Конфликты: пара правил -> одно исправленное на месте первого, второе уходит; каждое правило — в одной паре."""
    by_id = {x["id"]: x for x in rules}
    done = set()
    fixed = {}
    for pair in pairs:
        if len(pair) < 2 or pair[0] not in by_id or pair[1] not in by_id or pair[0] in done or pair[1] in done:
            continue
        a, b = by_id[pair[0]], by_id[pair[1]]
        r = ask_optimizer(model, CONFLICT, parse.scope_rule,
                          idx1=a["id"], rule1_text=a["rule"], rule1_rationale=a["rationale"],
                          idx2=b["id"], rule2_text=b["rule"], rule2_rationale=b["rationale"])
        if r:
            done |= {a["id"], b["id"]}
            fixed[a["id"]] = dict(rule=r[0], rationale=r[1], id=a["id"], confidence=max(confidence(a), confidence(b)))
    return [fixed.get(x["id"], x) for x in rules if x["id"] not in done or x["id"] in fixed]


def prune_subsumed(model, rules, pairs):
    """Поглощение: пара (общее, частное) — частное уходит, если модель подтвердила."""
    by_id = {x["id"]: x for x in rules}
    gone = set()
    for pair in pairs:
        if len(pair) < 2 or pair[0] not in by_id or pair[1] not in by_id:
            continue
        if ask_optimizer(model, SUBSUMED, parse.scope_subsumed, general_rule=by_id[pair[0]]["rule"],
                         specific_rule=by_id[pair[1]]["rule"]):
            gone.add(pair[1])
    return [x for x in rules if x["id"] not in gone]


def consolidate(model, rules, groups):
    """Слияние: группа правил -> одно на месте первого; не слилось — группа остаётся."""
    by_id = {x["id"]: x for x in rules}
    merged = {i for group in groups for i in group}
    out = [x for x in rules if x["id"] not in merged]
    for group in groups:
        members = [by_id[i] for i in group if i in by_id]
        if len(group) < 2 or not members:
            out += members
            continue
        # номера в промпте — из группы по порядку, как в апстриме (_merge_rules: indices[i]), даже если
        # какого-то номера среди правил нет
        numbered = [dict(x, id=i) for i, x in zip(group, members)]
        r = ask_optimizer(model, MERGE, parse.scope_rule, rules_text=render.rule_group(numbered))
        if r:
            out.append(dict(rule=r[0], rationale=r[1], id=members[0]["id"], confidence=max(map(confidence, members))))
        else:
            out += members
    return out


def optimize(model, rules, target):
    """optimize_rules: анализ, затем конфликты, поглощение, слияние — до OPTIMIZER_PASSES проходов, пока правил
    больше target; номера правил стабильны между проходами."""
    for i, x in enumerate(rules):
        x.setdefault("id", i)
    for _ in range(OPTIMIZER_PASSES):
        if len(rules) <= target:
            break
        if len(rules) > 1:
            analysis = ask_optimizer(model, ANALYZE, parse.scope_analysis, num_rules=len(rules),
                                     rules_text=render.rule_list(rules))
        else:
            analysis = parse.scope_analysis("")     # с одним правилом апстрим модель не зовёт
        if not (analysis["conflicts"] or analysis["subsumption"] or analysis["consolidation"]):
            break
        rules = resolve(model, rules, analysis["conflicts"])
        rules = prune_subsumed(model, rules, analysis["subsumption"])
        rules = consolidate(model, rules, analysis["consolidation"])
    return rules


def target_count(cap):
    return int(cap * TARGET_SHARE)


def compress(model, records, optimizer, target, cap, new):
    """Записи сверх cap сжимаются оптимизатором до target, остаток обрезается до cap. Нетронутая запись
    остаётся собой (id и статистика); исправленное и слитое — новые записи new(правило). Сбой оптимизатора
    (ответ не той формы) — только усечение, как в _optimize_domain_rules апстрима. У пунктов ACE (Lesson) нет
    rationale и confidence — берутся пустое и RULE_CONFIDENCE."""
    if len(records) <= cap:
        return records
    rules = []
    for r in records:
        rules.append(dict(rule=r.text, rationale=getattr(r, "rationale", ""),
                          confidence=getattr(r, "confidence", RULE_CONFIDENCE), record=r))
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
    def __init__(self, name=THOROUGHNESS, optimizer=optimize, cap=CAP, per_run=PER_RUN):
        self.name = name
        self.optimizer = optimizer
        self.cap = cap
        self.target = target_count(cap)
        self.per_run = per_run
        self.ids = Ids()
        self.domains = {}
        self.tactical = []
        self.accepted = 0       # принятых за прогон

    def records(self):
        return [r for rules in self.domains.values() for r in rules]

    def begin(self, k=0):
        """Новая попытка: tactical прошлой уходят — это срок жизни, а не правка."""
        self.tactical = []

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
        rules = rules + [Strategic(self.ids.next(), text, domain, rationale, confidence)]
        rules.sort(key=lambda r: r.confidence, reverse=True)

        def new(rule):
            return Strategic(self.ids.next(), rule["rule"], domain, rule["rationale"], rule["confidence"])
        self.domains[domain] = compress(ex.model, rules, self.optimizer, self.target, self.cap, new)

    def dump(self, suffix=""):
        """tactical, затем strategic по доменам; suffix — перспектива в имени вида, когда их несколько."""
        tactical = [dict(kind="tactical" + suffix, **r.dump()) for r in self.tactical]
        strategic = [dict(kind="strategic" + suffix, **r.dump()) for r in self.records()]
        return tactical + strategic


class Perspectives(Container):
    """Своя память у каждой перспективы; попытка k работает с памятью перспективы k. Урок идёт в память
    перспективы попытки, на которой он извлечён (attempt)."""
    requires = frozenset({CONFIDENCE, DOMAIN, RATIONALE, ATTEMPT})

    def __init__(self, names=(THOROUGHNESS,), **book):
        self.books = [Book(name, **book) for name in names]

    def book(self, k):
        return self.books[k % len(self.books)]

    def begin(self, k):
        self.book(k).begin()

    def learn(self, ex, extractions):
        for x in extractions:
            rows = zip(x.lessons, x.extras[CONFIDENCE], x.extras[DOMAIN], x.extras[RATIONALE], x.extras[ATTEMPT])
            for text, confidence, domain, rationale, k in rows:
                self.book(k).admit(ex, text, confidence, domain, rationale)

    def records(self):
        return [r for b in self.books for r in b.records()]

    def key(self):
        return tuple(b.key() for b in self.books)

    def dump(self):
        suffixes = len(self.books) > 1
        return [row for b in self.books for row in b.dump(f":{b.name}" if suffixes else "")]
