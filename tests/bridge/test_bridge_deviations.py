"""Идентификаторы записей DEVIATIONS.md уникальны: на них ссылаются тесты-мостик."""
from collections import Counter

from upstream import entries


def test_ids_unique():
    ids = entries()
    assert ids and not [i for i, n in Counter(ids).items() if n > 1]
