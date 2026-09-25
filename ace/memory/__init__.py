"""Память. Два мира, смешивать нельзя:

    уроки       записи со статистикой, правка структурированными операциями (lessons.py)
    документы   тексты без статистики, правка целиком или файловыми инструментами (documents.py, fs.py)

Запись (record.py) — id и неизменяемый текст; правка текста — новая запись. Память методов (куратор,
политики) — memory/<метод>.py, контейнеры наследует отсюда. Память объявляет requires — добавки, которые ей
нужны от извлечения (ace/extract), learn(ex, extractions) и begin(k) — начало попытки k (срок жизни записей)."""
from .documents import Document, Files
from .lessons import ALL, Container, Ids, Lessons, Operation, Sections
from .counters import HARMFUL, HELPFUL, Counted
from .record import HEAD_CHARS, Lesson, Record

__all__ = ["ALL", "Container", "Counted", "Document", "Files", "HARMFUL", "HEAD_CHARS", "HELPFUL", "Ids", "Lesson",
           "Lessons", "Operation", "Record", "Sections"]
