"""Файловые инструменты над миром документов (memory.Files) и записи памяти как файлы только на чтение (показ
каталогом). Точка монтирования — папка верхнего уровня: Files (rw или ro) или Records (всегда ro). Инструменты
получают FS через deps и чужую память не видят. Что видит модель (описания инструментов, отбивки) — prompts/fs.j2.

Правила как у агентских харнесов: читать обязательно только перед edit (видеть текущий текст для точной
замены: литеральная замена, old_string один раз, replace_all явно); create, append и delete — без чтения;
read постранично (offset, limit); папки — части пути, создаются вместе с файлом. Правки файлов идут под замком FS:
вызовы одного ответа модели pydantic-ai исполняет в потоках, и две правки одного файла не должны терять друг друга."""
import threading
from dataclasses import dataclass, field

from pydantic_ai import ModelRetry, RunContext

from . import prompts, render

READ_LIMIT = 2000           # строк за один read по умолчанию, как у харнесов
TEXT = prompts.macros("fs")


class Records:
    """Записи памяти как файлы только на чтение: имя — id, строка листинга — head(); прочитанное — в reads."""
    def __init__(self, records):
        self.by_id = {r.id: r for r in records}
        self.reads = []

    def ls(self, folder=""):
        if folder:
            return [], []
        return [], [(rid, r.head()) for rid, r in self.by_id.items()]

    def read(self, name):
        r = self.by_id.get(name)
        if r is None:
            return None
        if name not in self.reads:
            self.reads.append(name)
        return r.text


@dataclass
class Mount:
    store: object               # memory.Files или Records
    mode: str = "rw"            # rw | ro


@dataclass
class FS:
    mounts: dict                                # имя -> Mount
    seen: set = field(default_factory=set)      # прочитанные пути: без этого edit запрещён
    root: str = ""                              # абсолютный путь корня, как его видит агент (MCE: /workspace/...)
    lock: object = field(default_factory=threading.Lock, repr=False, compare=False)    # правки — по одной

    @property
    def reads(self):
        """id записей, прочитанных из Records (что решатель прочёл: episode.used)."""
        out = []
        for m in self.mounts.values():
            if isinstance(m.store, Records):
                out += m.store.reads
        return out

    def norm(self, path):
        """Путь без корня root и крайних слешей: «/workspace/iter1_sub0/context/a.md» -> «context/a.md»."""
        path, root = path.strip("/"), self.root.strip("/")
        if root and (path + "/").startswith(root + "/"):
            path = path[len(root):]
        return path.strip("/")

    def resolve(self, path):
        """Путь -> (точка монтирования, её Mount, путь внутри)."""
        name, _, rest = self.norm(path).partition("/")
        if name not in self.mounts:
            raise ModelRetry(TEXT.no_directory(name=name, available=", ".join(self.mounts)))
        return name, self.mounts[name], rest.strip("/")

    def text(self, path):
        _, m, rest = self.resolve(path)
        text = m.store.read(rest) if rest else None
        if text is None:
            raise ModelRetry(TEXT.no_file(path=path))
        return text

    def writable(self, path):
        name, m, rest = self.resolve(path)
        if m.mode != "rw":
            raise ModelRetry(TEXT.read_only(name=name))
        return m, rest


def listing(fs, path):
    """Содержимое папки строками: подпапки со слешем, файлы с краткой строкой."""
    name, m, rest = fs.resolve(path)
    folders, files = m.store.ls(rest)
    return render.listing(f"{name}/{rest}" if rest else name, folders, files)


def is_folder(fs, path):
    _, m, rest = fs.resolve(path)
    if not rest:
        return True
    return m.store.read(rest) is None and m.store.ls(rest) != ([], [])


@prompts.tool(TEXT.ls())
def ls(ctx: RunContext[FS], path: str = "") -> str:
    """Без пути — точки монтирования с режимом, с папкой — её содержимое."""
    fs = ctx.deps
    if not fs.norm(path):
        return render.mounts((name, m.mode) for name, m in fs.mounts.items())
    return listing(fs, path)


@prompts.tool(TEXT.read())
def read(ctx: RunContext[FS], path: str, offset: int = 1, limit: int = READ_LIMIT) -> str:
    """Страница файла с номерами строк; если файл длиннее — в конце сколько осталось и откуда читать. Папка —
    листинг."""
    fs = ctx.deps
    if is_folder(fs, path):
        return listing(fs, path)
    lines = fs.text(path).splitlines()
    fs.seen.add(fs.norm(path))
    start = max(offset, 1)
    shown = lines[start - 1:start - 1 + limit]
    page = render.numbered_lines(shown, start)
    left = len(lines) - (start - 1 + len(shown))
    if left <= 0:
        return page
    return page + "\n" + TEXT.more_lines(left=left, offset=start + len(shown))


@prompts.tool(TEXT.create())
def create(ctx: RunContext[FS], path: str, content: str) -> str:
    m, rest = ctx.deps.writable(path)
    if not rest:
        raise ModelRetry(TEXT.need_file_path())
    with ctx.deps.lock:
        if m.store.read(rest) is not None:
            raise ModelRetry(TEXT.exists(path=path))
        m.store.write(rest, content.strip())
    return path.strip("/")


@prompts.tool(TEXT.append())
def append(ctx: RunContext[FS], path: str, text: str) -> str:
    m, rest = ctx.deps.writable(path)
    with ctx.deps.lock:
        old = ctx.deps.text(path)
        m.store.write(rest, old.rstrip("\n") + "\n" + text.strip())
    return TEXT.done()


@prompts.tool(TEXT.edit())
def edit(ctx: RunContext[FS], path: str, old_string: str, new_string: str, replace_all: bool = False) -> str:
    m, rest = ctx.deps.writable(path)
    with ctx.deps.lock:
        text = ctx.deps.text(path)
        if ctx.deps.norm(path) not in ctx.deps.seen:
            raise ModelRetry(TEXT.read_first(path=path))
        n = text.count(old_string)
        if n == 0:
            raise ModelRetry(TEXT.not_found())
        if n > 1 and not replace_all:
            raise ModelRetry(TEXT.occurs(n=n))
        m.store.write(rest, text.replace(old_string, new_string).strip())
    return TEXT.done()


@prompts.tool(TEXT.delete())
def delete(ctx: RunContext[FS], path: str) -> str:
    m, rest = ctx.deps.writable(path)
    with ctx.deps.lock:
        ctx.deps.text(path)
        m.store.delete(rest)
    return TEXT.done()


READ_TOOLS = (ls, read)
TOOLS = (ls, read, create, append, edit, delete)
