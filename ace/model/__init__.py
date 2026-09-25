"""Доступ к модели: вызов Call(messages, params, reader), ответ Reply; model.ask(call).

    messages    сообщения ровно как уходят модели: список {"role", "content"} — у одних апстримов только user,
                у других system + user, у третьих история; пустой системный промпт не отправляется (messages())
    params      параметры запроса ровно как уходят: temperature, top_p, max_tokens, ...; чего нет — у сервера по
                умолчанию (params() — умолчания стенда: T = 0 и общий предел генерации)
    reader      разбор ответа: Reader(text=разборщик, schema=pydantic-модель); по умолчанию текст как есть

Бэкенды (config.BACKEND или Model(backend=...)):
    pydantic-ai     по умолчанию, для абляций: структурированный вывод по схеме, инструменты, шаговый режим с Patch
                    (agent.py)
    wire            «провод апстрима»: официальный клиент openai, chat.completions.create ровно с messages и params
                    вызова, без своей логики; ответ текстом -> reader (wire.py)
Вызов с инструментами (решатель с run_python, агенты mce_fs) идёт только через pydantic-ai; агенты mce — Claude
Agent SDK (claude.py). Агентный цикл апстрима
(TF-GRPO: openai-agents) идёт проводом при любом бэкенде: model.message(messages, params) -> ответ как есть.
Эмбеддинги — model.embed(texts, name): провод — /v1/embeddings сервера с моделью name, как у апстрима (EvoLib),
pydantic-ai — BGE-M3 стенда (ace.embed); сервер эмбеддингов стенда — тот же BGE-M3 (tools/record/embeddings.py)."""
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, NamedTuple

from .. import config, embed, parse


@dataclass(frozen=True)
class Reader:
    """Разбор ответа. text(ответ текстом или None) -> значение: порт разборщика апстрима. schema — pydantic-модель
    ответа: pydantic-ai отдаёт её структурированным выводом, провод — текстом, который разбирает text, а без него
    общий разбор JSON в схему (parse.structured)."""
    text: Callable = None
    schema: type = None

    def read(self, raw):
        if self.text is not None:
            return self.text(raw)
        if self.schema is not None:
            return parse.structured(raw, self.schema)
        return raw


TEXT = Reader()


@dataclass
class Call:
    messages: list
    params: dict = field(default_factory=dict)
    reader: Reader = TEXT
    # только pydantic-ai: инструменты решателя и агентов, шаговый режим, продолжение разговора с инструментами
    tools: tuple = ()
    deps: object = None
    rounds: int = 0             # раундов инструментов до ответа
    on_step: Callable = None    # on_step(новые шаги) -> Patch | None
    history: list = None        # Reply.messages прошлого вызова: messages продолжают тот же разговор


def messages(user, system=""):
    """Системный (если не пустой) и пользовательский."""
    return ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": user}]


def parts(user):
    """Одно сообщение user с содержимым частями [{"type": "text"}], как шлёт SCOPE (OpenAIAdapter)."""
    return [{"role": "user", "content": [{"type": "text", "text": user}]}]


def content(m):
    """Текст сообщения; содержимое частями — их тексты подряд."""
    c = m["content"]
    return c if isinstance(c, str) else "".join(x.get("text", "") for x in c)


def roles(messages):
    """(системный или "", последний пользовательский) — модели-заглушки, трасса."""
    system = next((content(m) for m in messages if m["role"] == "system"), "")
    return system, next((content(m) for m in reversed(messages) if m["role"] == "user"), "")


def params(temperature=0, top_p=None, max_tokens=None):
    """Параметры запроса стенда: температура и общий предел генерации (config.MAX_TOKENS); None — не передаётся."""
    p = dict(max_tokens=max_tokens or config.MAX_TOKENS, temperature=temperature, top_p=top_p)
    return {k: v for k, v in p.items() if v is not None}


class Outcome(Enum):
    """Чем кончился вызов."""
    answer = "answer"       # модель ответила
    step = "step"           # кончился лимит запросов: шаг сделан, ответа ещё нет
    broken = "broken"       # модель сломалась: вывод не прошёл схему после всех попыток (UnexpectedModelBehavior)


class Step(NamedTuple):
    """Шаг попытки: вызов инструмента и его результат (отбивка — «Error: ...»)."""
    tool: str
    args: str
    result: str

    @property
    def failed(self):
        """Отбивка: traceback исполнения или ошибка вызова (ModelRetry, аргументы не той формы)."""
        return "Traceback" in self.result or self.result.startswith("Error")


@dataclass
class Patch:
    """Вмешательство посреди попытки, до следующего запроса к модели.
    system — новый системный промпт целиком (SCOPE, как в апстриме; префикс истории меняется);
    append — сообщение в конец истории, после результатов инструментов (префикс цел);
    tool_result — текст к результату последнего инструмента (урок прямо в отбивке)."""
    system: str = None
    append: str = None
    tool_result: str = None

    def merge(self, other):
        """Два вмешательства одного шага: системный промпт — последний, дописывания — подряд."""
        join = lambda a, b: "\n\n".join(x for x in (a, b) if x) or None
        return Patch(other.system if other.system is not None else self.system,
                     join(self.append, other.append), join(self.tool_result, other.tool_result))


@dataclass
class Reply:
    output: object          # то, что вернул reader; None, если модель не справилась
    text: str               # вся траектория текстом: ответы, вызовы tools, их результаты
    truncated: bool = False
    steps: list = field(default_factory=list)   # шаги: Step(имя, аргументы, результат)
    outcome: Outcome = Outcome.answer
    messages: list = None   # вся история бэкенда: продолжить разговор (Call.history)
    raw: str = None         # последний ответ модели текстом, до разбора reader


def text_reply(call, text, truncated=False):
    """Ответ текстом, разобранный читателем вызова (провод, модели-заглушки)."""
    return Reply(call.reader.read(text), text or "", truncated, raw=text)


class Model:
    """Модель стенда: вызовы идут в выбранный бэкенд, вызовы с инструментами — в pydantic-ai."""
    def __init__(self, name=None, base_url=None, backend=None):
        from .agent import PydanticAI
        from .wire import Wire
        self.name = name or config.MODEL
        base_url = self.base_url = base_url or config.OPENAI_BASE_URL
        self.backend = backend or config.BACKEND
        if self.backend not in ("pydantic-ai", "wire"):
            raise ValueError(f"неизвестный бэкенд модели: {self.backend}")
        self.agent = PydanticAI(self.name, base_url)
        self.wire = Wire(self.name, base_url) if self.backend == "wire" else None
        self.direct = self.wire or Wire(self.name, base_url)    # model.message: провод при любом бэкенде

    def ask(self, call):
        if self.wire is None or call.tools or call.history is not None:
            return self.agent.ask(call)
        return self.wire.ask(call)

    def message(self, messages, params):
        """(сообщение assistant dict, finish_reason): запрос ровно с messages и params (с tools), ответ с tool_calls."""
        return self.direct.message(messages, params)

    def embed(self, texts, name):
        """Векторы texts списками: провод — запрос /v1/embeddings с моделью name, иначе BGE-M3 стенда."""
        if self.wire is not None:
            return self.wire.embed(texts, name)
        return embed.embed(texts).tolist()

    def usage(self):
        return {k: sum(getattr(b, k) for b in (self.agent, self.direct)) for k in ("calls", "prompt_tokens", "completion_tokens")}
