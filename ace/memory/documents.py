"""Мир документов: тексты без статистики, учёт — по версии памяти целиком (мета).

    Document    один текст, переписывается целиком (DC)
    Files       файлы и папки: путь -> текст, правка инструментами fs.py (MCE)"""
from .record import Record


class Document:
    requires = frozenset()

    def __init__(self, text="", kind="document"):
        self.text, self.kind = text, kind

    def rewrite(self, text):
        self.text = text

    def begin(self, k):
        pass

    def records(self):
        return [Record(self.kind, self.text)] if self.text else []

    def chars(self):
        return len(self.text)

    def key(self):
        return self.text

    def dump(self):
        return [dict(kind=self.kind, id=self.kind, text=self.text)] if self.text else []


class Files:
    """Путь — строка «папка/подпапка/имя»; папки существуют, пока в них есть файлы."""
    requires = frozenset()

    def __init__(self, kind="file"):
        self.kind, self.files = kind, {}

    @classmethod
    def of(cls, files, kind="folder"):
        """Папка из словаря путь -> текст (монтируется только на чтение)."""
        out = cls(kind)
        out.files = dict(files)
        return out

    def begin(self, k):
        pass

    def read(self, path):
        return self.files.get(path)

    def write(self, path, text):
        self.files[path] = text

    def delete(self, path):
        self.files.pop(path, None)

    def ls(self, folder=""):
        """Прямое содержимое папки: (подпапки, [(имя, краткая строка)])."""
        prefix = folder.strip("/") + "/" if folder.strip("/") else ""
        folders, files = [], []
        for path in sorted(self.files):
            if not path.startswith(prefix):
                continue
            name, sep, _ = path[len(prefix):].partition("/")
            if sep:
                if name not in folders:
                    folders.append(name)
            else:
                files.append((name, Record(path, self.files[path]).head()))
        return folders, files

    def records(self):
        return [Record(p, t) for p, t in self.files.items()]

    def chars(self):
        return sum(len(t) for t in self.files.values())

    def key(self):
        return tuple(sorted(self.files.items()))

    def dump(self):
        return [dict(kind=self.kind, id=p, text=t) for p, t in self.files.items()]
