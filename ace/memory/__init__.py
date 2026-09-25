"""Память. Два мира, смешивать нельзя:

    уроки       записи со статистикой, правка структурированными операциями (lessons.py)
    документы   тексты без статистики, правка целиком или файловыми инструментами (documents.py, fs.py)

Запись (record.py) — id и неизменяемый текст; правка текста — новая запись. Реализации памяти методов
(куратор, политики) лежат рядом с методами и наследуют контейнеры отсюда. Память метода объявляет
requires — добавки, которые ей нужны от извлечения (ace/extract), и learn(ex, extractions)."""
from .documents import Document, Files
from .lessons import ALL, Container, Ids, Lessons, Operation, Sections
from .record import HARMFUL, HEAD_CHARS, HELPFUL, Lesson, Record

__all__ = ["ALL", "Container", "Document", "Files", "HARMFUL", "HEAD_CHARS", "HELPFUL", "Ids", "Lesson", "Lessons",
           "Operation", "Record", "Sections"]
