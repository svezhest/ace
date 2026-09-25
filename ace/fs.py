"""Файловые инструменты над миром документов (memory.Files) и каталог записей только на чтение (показ).
Точка монтирования — папка верхнего уровня: Files (rw или ro) или Catalog (всегда ro). Инструменты получают
FS через deps и чужую память не видят.

Правила как у агентских харнесов: читать обязательно только перед edit (видеть текущий текст для точной
замены: литеральная замена, old_string один раз, replace_all явно); create, append и delete — без чтения;
read постранично (offset, limit); папки — части пути, создаются вместе с файлом."""
from dataclasses import dataclass, field

from pydantic_ai import ModelRetry, RunContext

from . import render

READ_LIMIT = 2000           # строк за один read по умолчанию, как у харнесов


class Catalog:
    """Записи как файлы только на чтение: имя — id, строка каталога — head(); прочитанное — в reads."""
    def __init__(self, records):
        self.by_id = {r.id: r for r in records}
        self.reads = []

    def ls(self, folder=""):
        return [], [] if folder else [(id, r.head()) for id, r in self.by_id.items()]

    def read(self, name):
        r = self.by_id.get(name)
        if r is None:
            return None
        if name not in self.reads:
            self.reads.append(name)
        return r.text


@dataclass
class Mount:
    store: object               # memory.Files или Catalog
    mode: str = "rw"            # rw | ro


@dataclass
class FS:
    mounts: dict                                # имя -> Mount
    seen: set = field(default_factory=set)      # прочитанные пути: без этого edit запрещён

    @property
    def reads(self):
        """id записей, прочитанных из каталогов (что решатель прочёл: episode.used)."""
        return [id for m in self.mounts.values() if isinstance(m.store, Catalog) for id in m.store.reads]

    def split(self, path):
        """Путь -> (точка монтирования, её Mount, путь внутри)."""
        name, _, rest = path.strip("/").partition("/")
        if name not in self.mounts:
            raise ModelRetry(f"no such directory: {name}. Available: {', '.join(self.mounts)}")
        return name, self.mounts[name], rest.strip("/")

    def text(self, path):
        _, m, rest = self.split(path)
        text = m.store.read(rest) if rest else None
        if text is None:
            raise ModelRetry(f"no such file: {path}")
        return text

    def writable(self, path):
        name, m, rest = self.split(path)
        if m.mode != "rw":
            raise ModelRetry(f"{name} is read-only")
        return m, rest


def listing(fs, path):
    """Содержимое папки строками: подпапки со слешем, файлы с краткой строкой."""
    name, m, rest = fs.split(path)
    folders, files = m.store.ls(rest)
    base = f"{name}/{rest}" if rest else name
    return "\n".join([f"{base}/{d}/" for d in folders] + [f"{base}/{f}  {head}" for f, head in files]) or render.EMPTY


def is_folder(fs, path):
    _, m, rest = fs.split(path)
    return not rest or m.store.read(rest) is None and m.store.ls(rest) != ([], [])


def ls(ctx: RunContext[FS], path: str = "") -> str:
    """List a directory. Without a path lists the top-level directories; with a directory lists its
    subdirectories and files, each file with its first line."""
    fs = ctx.deps
    if not path.strip("/"):
        return "\n".join(f"{n}/  ({m.mode})" for n, m in fs.mounts.items())
    return listing(fs, path)


def read(ctx: RunContext[FS], path: str, offset: int = 1, limit: int = READ_LIMIT) -> str:
    """Read a file from line `offset` (1-based), at most `limit` lines. Lines are numbered `N: text`;
    never copy the `N: ` prefix into an edit. A directory path lists the directory."""
    fs = ctx.deps
    if is_folder(fs, path):
        return listing(fs, path)
    lines = fs.text(path).splitlines()
    fs.seen.add(path.strip("/"))
    start = max(offset, 1)
    shown = lines[start - 1:start - 1 + limit]
    out = "\n".join(f"{i}: {l}" for i, l in enumerate(shown, start))
    left = len(lines) - (start - 1 + len(shown))
    return out + "\n" + render.more_lines(left, start + len(shown)) if left > 0 else out


def create(ctx: RunContext[FS], path: str, content: str) -> str:
    """Create a new file; folders in the path are created with it. Returns its path."""
    m, rest = ctx.deps.writable(path)
    if not rest:
        raise ModelRetry("give a file path inside a directory, e.g. context/notes.md")
    if m.store.read(rest) is not None:
        raise ModelRetry(f"{path} already exists; use edit or append")
    m.store.write(rest, content.strip())
    return path.strip("/")


def append(ctx: RunContext[FS], path: str, text: str) -> str:
    """Append text as new lines at the end of a file."""
    m, rest = ctx.deps.writable(path)
    old = ctx.deps.text(path)
    m.store.write(rest, old.rstrip("\n") + "\n" + text.strip())
    return "ok"


def edit(ctx: RunContext[FS], path: str, old_string: str, new_string: str, replace_all: bool = False) -> str:
    """Replace old_string with new_string. old_string must occur exactly once unless replace_all.
    An empty new_string deletes the fragment. Read the file before editing it."""
    m, rest = ctx.deps.writable(path)
    text = ctx.deps.text(path)
    if path.strip("/") not in ctx.deps.seen:
        raise ModelRetry(f"read {path} before editing it")
    n = text.count(old_string)
    if n == 0:
        raise ModelRetry("old_string not found in the file")
    if n > 1 and not replace_all:
        raise ModelRetry(f"old_string occurs {n} times; add surrounding context or set replace_all")
    m.store.write(rest, text.replace(old_string, new_string).strip())
    return "ok"


def delete(ctx: RunContext[FS], path: str) -> str:
    """Delete a file."""
    m, rest = ctx.deps.writable(path)
    ctx.deps.text(path)
    m.store.delete(rest)
    return "ok"


READ_TOOLS = (ls, read)
TOOLS = (ls, read, create, append, edit, delete)
