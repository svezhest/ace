"""Фейковая модель для снятия эталонов с апстримов.

Пишет каждый запрос и отвечает заготовкой, выбранной по маркеру в тексте промпта или по его хэшу,
а не по номеру вызова: у части апстримов порядок вызовов недетерминирован. Никогда не бросает —
иначе апстримы уходят в ретраи со sleep. Без зависимостей, импортируется из любого venv.
"""
import hashlib
import inspect
import json
import os
import subprocess
import sys
import threading
from types import SimpleNamespace

BRIDGE = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.join(BRIDGE, "fixtures")
UPSTREAMS = os.environ.get("UPSTREAMS", "/Users/user/Projects/upstreams")
# до offline(): он меняет cwd на tmp
SCRIPT = os.path.abspath(sys.argv[0]) if sys.argv and sys.argv[0] else ""


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def text_of(messages):
    """Весь текст запроса одной строкой (для маркеров и хэша)."""
    if isinstance(messages, str):
        return messages
    parts = []
    for m in messages:
        c = m.get("content") if isinstance(m, dict) else getattr(m, "content", m)
        if isinstance(c, list):
            c = "".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in c)
        parts.append(f"[{m.get('role', '?') if isinstance(m, dict) else '?'}]\n{c}")
    return "\n".join(parts)


class FakeLLM:
    """rules: список (маркер, ответ); маркер — подстрока или функция от текста; ответ — строка
    или функция от текста. by_hash: {digest(текст): ответ} проверяется первым."""

    def __init__(self, rules=(), by_hash=None, default=""):
        self.rules = list(rules)
        self.by_hash = dict(by_hash or {})
        self.default = default
        self.calls = []
        self._lock = threading.Lock()

    def answer(self, text):
        h = digest(text)
        if h in self.by_hash:
            return self.by_hash[h], f"hash:{h}"
        for i, (marker, reply) in enumerate(self.rules):
            hit = marker(text) if callable(marker) else marker in text
            if hit:
                return (reply(text) if callable(reply) else reply), f"rule:{i}"
        return self.default, "default"

    def __call__(self, messages, **params):
        text = text_of(messages)
        reply, how = self.answer(text)
        rec = {
            "messages": messages if not isinstance(messages, str) else None,
            "prompt": messages if isinstance(messages, str) else None,
            "hash": digest(text),
            "matched": how,
            "response": reply,
        }
        for k in ("model", "temperature", "max_tokens", "max_completion_tokens",
                  "response_format", "top_p", "n", "stop"):
            if k in params:
                rec[k] = params[k]
        with self._lock:
            self.calls.append(rec)
        return reply

    # OpenAI-подобный клиент поверх этой модели
    def client(self, embed=None):
        return FakeOpenAI(self, embed)


def _response(reply):
    usage = SimpleNamespace(prompt_tokens=0, completion_tokens=0, total_tokens=0)
    msg = SimpleNamespace(content=reply, role="assistant", tool_calls=None, reasoning_content=None)
    choice = SimpleNamespace(message=msg, finish_reason="stop", index=0)
    return SimpleNamespace(choices=[choice], usage=usage, model="fake", id="fake")


class _Completions:
    def __init__(self, llm):
        self.llm = llm

    def create(self, messages=None, **kw):
        return _response(self.llm(messages, **kw))


class _AsyncCompletions(_Completions):
    async def create(self, messages=None, **kw):
        return _response(self.llm(messages, **kw))


class _Embeddings:
    def __init__(self, embed, calls):
        self.embed = embed
        self.calls = calls

    def create(self, input=None, model=None, **kw):
        items = [input] if isinstance(input, str) else list(input)
        self.calls.append({"model": model, "input": items})
        data = [SimpleNamespace(embedding=list(self.embed(s)), index=i) for i, s in enumerate(items)]
        return SimpleNamespace(data=data, usage=SimpleNamespace(prompt_tokens=0, total_tokens=0))


class FakeOpenAI:
    def __init__(self, llm, embed=None, asynchronous=False):
        comp = _AsyncCompletions(llm) if asynchronous else _Completions(llm)
        self.chat = SimpleNamespace(completions=comp)
        self.embedding_calls = []
        self.embeddings = _Embeddings(embed or (lambda s: [1.0, 0.0]), self.embedding_calls)


class TableEmbed:
    """Эмбеддинги из таблицы: подстрока -> вектор; иначе вектор по умолчанию."""

    def __init__(self, table, default=(0.0, 0.0, 1.0)):
        self.table = list(table.items()) if isinstance(table, dict) else list(table)
        self.default = list(default)

    def __call__(self, s):
        for key, vec in self.table:
            if key in s:
                return list(vec)
        return list(self.default)


# --- эталоны -------------------------------------------------------------------------------------

def git_head(path):
    try:
        return subprocess.check_output(["git", "-C", path, "rev-parse", "HEAD"], text=True).strip()
    except Exception:
        return None


def where(obj, root):
    """file:line функции или класса относительно корня апстрима."""
    obj = inspect.unwrap(obj)
    f = inspect.getsourcefile(obj)
    line = inspect.getsourcelines(obj)[1]
    return f"{os.path.relpath(f, root)}:{line}"


def header(repo, funcs, command=None):
    root = os.path.join(UPSTREAMS, repo)
    return {
        "repo": repo,
        "path": root,
        "commit": git_head(root),
        "functions": {name: where(f, root) if not isinstance(f, str) else f for name, f in funcs.items()},
        # запуск из корня стенда
        "command": command or "$UPSTREAMS/{} {}".format(
            os.path.relpath(sys.executable, UPSTREAMS), os.path.relpath(SCRIPT, os.path.dirname(BRIDGE))),
        "python": sys.version.split()[0],
    }


def _plain(x):
    if isinstance(x, (str, int, float, bool)) or x is None:
        return x
    if isinstance(x, dict):
        return {str(k): _plain(v) for k, v in x.items()}
    if isinstance(x, (list, tuple, set)):
        items = [_plain(v) for v in x]
        return sorted(items, key=repr) if isinstance(x, set) else items
    if hasattr(x, "tolist"):
        return x.tolist()
    if hasattr(x, "model_dump"):
        return _plain(x.model_dump())
    if hasattr(x, "__dict__"):
        return {"__type__": type(x).__name__, **_plain(vars(x))}
    return repr(x)


def write(method, name, head, data):
    """bridge/fixtures/<method>/<name>.json: {"header": ..., "data": ...}."""
    d = os.path.join(FIXTURES, method)
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, f"{name}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"header": head, "data": _plain(data)}, f, ensure_ascii=False, indent=1)
        f.write("\n")
    print("wrote", os.path.relpath(path, os.path.dirname(BRIDGE)))
    return path


def call(fn, *args, **kwargs):
    """Результат или исключение как данные — для разборщиков на неудобных входах."""
    try:
        return {"ok": _plain(fn(*args, **kwargs))}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


def offline(seed=0):
    """Общая подготовка: кэш tiktoken, пустой tmp cwd (нет .env для load_dotenv), фиктивные ключи."""
    import random
    import tempfile
    os.environ.setdefault("TIKTOKEN_CACHE_DIR", os.path.join(UPSTREAMS, ".tiktoken"))
    for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "TOGETHER_API_KEY", "SAMBANOVA_API_KEY"):
        os.environ[k] = "fake"
    for k in ("OPENAI_BASE_URL", "OPENAI_API_BASE"):
        os.environ.pop(k, None)
    tmp = tempfile.mkdtemp(prefix="bridge-")
    os.chdir(tmp)
    random.seed(seed)
    try:
        import numpy as np
        np.random.seed(seed)
    except ImportError:
        pass
    return tmp
