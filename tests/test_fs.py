"""fs: мир документов (Files) и каталог записей только на чтение. Читать обязательно только перед edit,
read постранично, папки — части пути."""
import pytest
from pydantic_ai import ModelRetry

from ace import fs
from ace.memory import Files, Lesson, Record


class Ctx:
    """Подстановка RunContext: инструментам нужен только deps."""
    def __init__(self, deps):
        self.deps = deps


def files():
    store = Files()
    store.write("notes.md", "Check units.\nSecond line.")
    store.write("math/ratios.md", "Divide carefully.")
    return Ctx(fs.FS({"context": fs.Mount(store), "data": fs.Mount(Files(), "ro")})), store


def test_folders():
    ctx, store = files()
    assert fs.ls(ctx) == "context/  (rw)\ndata/  (ro)"
    assert fs.ls(ctx, "context") == "context/math/\ncontext/notes.md  Check units."
    assert fs.ls(ctx, "context/math") == "context/math/ratios.md  Divide carefully."
    assert fs.read(ctx, "context/math") == fs.ls(ctx, "context/math")
    assert fs.create(ctx, "context/a/b/new.md", "x") == "context/a/b/new.md"
    assert "context/a/" in fs.ls(ctx, "context") and store.read("a/b/new.md") == "x"


def test_edit_needs_read():
    ctx, store = files()
    with pytest.raises(ModelRetry, match="read context/notes.md"):
        fs.edit(ctx, "context/notes.md", "units", "signs")
    fs.read(ctx, "context/notes.md")
    assert fs.edit(ctx, "context/notes.md", "units", "signs") == "ok"
    assert store.read("notes.md") == "Check signs.\nSecond line."


def test_append_delete_without_read():
    ctx, store = files()
    fs.append(ctx, "context/notes.md", "Third line.")
    assert store.read("notes.md").splitlines()[-1] == "Third line."
    fs.delete(ctx, "context/math/ratios.md")
    assert store.read("math/ratios.md") is None and fs.ls(ctx, "context") == "context/notes.md  Check units."


def test_read_pages():
    ctx, store = files()
    store.write("long.md", "\n".join(f"line {i}" for i in range(1, 8)))
    assert fs.read(ctx, "context/long.md", limit=3) == "1: line 1\n2: line 2\n3: line 3\n... 4 more lines; read with offset=4"
    assert fs.read(ctx, "context/long.md", offset=6) == "6: line 6\n7: line 7"


def test_read_only_and_errors():
    ctx, _ = files()
    with pytest.raises(ModelRetry, match="read-only"):
        fs.create(ctx, "data/x.md", "x")
    with pytest.raises(ModelRetry, match="no such file"):
        fs.read(ctx, "context/missing.md")
    with pytest.raises(ModelRetry, match="no such directory"):
        fs.ls(ctx, "memory")
    with pytest.raises(ModelRetry, match="already exists"):
        fs.create(ctx, "context/notes.md", "x")


def test_catalog_read_only_and_tracked():
    records = [Lesson("r1", "Check units.\nMore."), Record("r2", "Guard division.")]
    ctx = Ctx(fs.FS({"skills": fs.Mount(fs.Records(records), "ro")}))
    assert fs.listing(ctx.deps, "skills") == "skills/r1  Check units.\nskills/r2  Guard division."
    assert fs.read(ctx, "skills/r2") == "1: Guard division."
    fs.read(ctx, "skills/r2")
    assert ctx.deps.reads == ["r2"]
    with pytest.raises(ModelRetry, match="read-only"):
        fs.edit(ctx, "skills/r2", "Guard", "x")


def test_empty_listing():
    ctx = Ctx(fs.FS({"skills": fs.Mount(fs.Records([]), "ro")}))
    assert fs.listing(ctx.deps, "skills") == "(empty)"


def test_root_paths():
    """Пути от корня root (агенты MCE видят /workspace/...) и относительные — одно и то же, в том числе для edit."""
    ctx, store = files()
    ctx.deps.root = "/workspace/iter1_sub0"
    assert fs.ls(ctx, "/workspace/iter1_sub0") == fs.ls(ctx)
    fs.read(ctx, "/workspace/iter1_sub0/context/notes.md")
    assert fs.edit(ctx, "context/notes.md", "units", "signs") == "ok"
    fs.create(ctx, "/workspace/iter1_sub0/context/new.md", "x")
    assert store.read("new.md") == "x"


def test_parallel_edits_keep_both():
    """Две правки одного файла из одного ответа (pydantic-ai исполняет их в потоках) — обе в файле."""
    import threading
    import time
    ctx, store = files()
    ctx.deps.seen.add("context/notes.md")
    read = store.read
    store.read = lambda path: (read(path), time.sleep(0.05))[0]     # шире окно гонки
    edits = [threading.Thread(target=fs.edit, args=(ctx, "context/notes.md", old, old.upper()))
             for old in ("Check", "Second")]
    for t in edits:
        t.start()
    for t in edits:
        t.join()
    assert store.files["notes.md"] == "CHECK units.\nSECOND line."
