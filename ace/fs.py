"""Виртуальная файловая система поверх памяти. Запись = файл, точка монтирования = набор записей
с режимом доступа. Инструменты получают FS через deps и чужую память не видят.
Правила edit те же, что у агентских харнесов: литеральная замена, old_string один раз, replace_all
явно, перед правкой файл надо прочитать. Сверх режима монтирования действует схема памяти."""
from dataclasses import dataclass, field

from pydantic_ai import ModelRetry, RunContext

from .memory import Forbidden, Memory


@dataclass
class Mount:
    memory: Memory
    kinds: tuple = ()          # какие записи видны; () = все
    mode: str = "rw"           # rw | ro
    track: bool = False        # чтения складывать в FS.reads


@dataclass
class FS:
    mounts: dict               # имя -> Mount
    seen: set = field(default_factory=set)    # что уже читали: без этого правка запрещена
    reads: list = field(default_factory=list) # id прочитанных записей с отслеживаемых точек

    def split(self, path):
        name, _, id = path.strip("/").partition("/")
        if name not in self.mounts:
            raise ModelRetry(f"no such directory: {name}. Available: {', '.join(self.mounts)}")
        return name, self.mounts[name], id

    def record(self, path):
        name, m, id = self.split(path)
        rec = m.memory.get(id)
        if not rec or (m.kinds and rec.kind not in m.kinds):
            raise ModelRetry(f"no such file: {path}")
        return m, rec

    def writable(self, path):
        m, rec = self.record(path)
        if m.mode != "rw":
            raise ModelRetry(f"{path} is read-only")
        if path not in self.seen:
            raise ModelRetry(f"read {path} before changing it")
        return m, rec


def listing(fs, name):
    m = fs.mounts[name]
    return "\n".join(f"{name}/{r.id}  {r.when or r.text.splitlines()[0][:80]}" for r in m.memory.of(*m.kinds)) or "(empty)"


def ls(ctx: RunContext[FS], path: str = "") -> str:
    """List files. Without a path lists the directories; with a directory lists its files with their first line."""
    fs = ctx.deps
    if not path:
        return "\n".join(f"{n}/  ({m.mode})" for n, m in fs.mounts.items())
    name, m, _ = fs.split(path)
    return listing(fs, name)


def read(ctx: RunContext[FS], path: str) -> str:
    """Read a file. Lines are numbered `N: text`; never copy the `N: ` prefix into an edit."""
    if "/" not in path.strip("/"):
        return ls(ctx, path)
    m, rec = ctx.deps.record(path)
    ctx.deps.seen.add(path)
    if m.track and rec.id not in ctx.deps.reads:
        ctx.deps.reads.append(rec.id)
    return "\n".join(f"{i}: {l}" for i, l in enumerate(rec.text.splitlines(), 1))


def create(ctx: RunContext[FS], directory: str, content: str) -> str:
    """Create a new file in a directory. Returns its path."""
    name, m, _ = ctx.deps.split(directory)
    if m.mode != "rw":
        raise ModelRetry(f"{name} is read-only")
    try:
        rec = m.memory.add(content.strip(), kind=m.kinds[0] if m.kinds else None)
    except Forbidden as e:
        raise ModelRetry(str(e))
    ctx.deps.seen.add(f"{name}/{rec.id}")
    return f"{name}/{rec.id}"


def append(ctx: RunContext[FS], path: str, text: str) -> str:
    """Append text as new lines at the end of a file."""
    m, rec = ctx.deps.writable(path)
    try:
        m.memory.edit(rec.id, rec.text.rstrip("\n") + "\n" + text.strip())
    except Forbidden as e:
        raise ModelRetry(str(e))
    return "ok"


def edit(ctx: RunContext[FS], path: str, old_string: str, new_string: str, replace_all: bool = False) -> str:
    """Replace old_string with new_string. old_string must occur exactly once unless replace_all.
    An empty new_string deletes the fragment."""
    m, rec = ctx.deps.writable(path)
    n = rec.text.count(old_string)
    if n == 0:
        raise ModelRetry("old_string not found in the file")
    if n > 1 and not replace_all:
        raise ModelRetry(f"old_string occurs {n} times; add surrounding context or set replace_all")
    try:
        m.memory.edit(rec.id, rec.text.replace(old_string, new_string).strip())
    except Forbidden as e:
        raise ModelRetry(str(e))
    return "ok"


def delete(ctx: RunContext[FS], path: str) -> str:
    """Delete a file."""
    m, rec = ctx.deps.writable(path)
    try:
        m.memory.drop(rec.id)
    except Forbidden as e:
        raise ModelRetry(str(e))
    return "ok"


READ_TOOLS = (ls, read)
TOOLS = (ls, read, create, append, edit, delete)
