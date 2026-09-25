"""Каталог fs на записях разных классов: краткая строка — head() записи."""
from ace import fs
from ace.memory import Bullet, Entry, Hook, Kind, Memory


def test_listing_uses_head():
    memory = Memory({"bullet": Kind(Bullet), "entry": Kind(Entry), "hook": Kind(Hook)})
    memory.add("Check units.\nSecond line.", "bullet")
    memory.add("Guard the division.", "entry", when="dividing")
    memory.add("Check the denominator.", "hook", trigger="ZeroDivisionError")
    files = fs.FS({"memory": fs.Mount(memory)})
    assert fs.listing(files, "memory").splitlines() == [
        "memory/r1  Check units.", "memory/r2  dividing", "memory/r3  ZeroDivisionError"]


def test_listing_empty():
    files = fs.FS({"memory": fs.Mount(Memory({"bullet": Kind(Bullet)}))})
    assert fs.listing(files, "memory") == "(empty)"
