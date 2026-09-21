"""Память: список записей. Методы различаются тем, как её пишут и как показывают решателю."""
import json
from dataclasses import dataclass, field, asdict


@dataclass
class Record:
    id: str
    text: str
    kind: str = "insight"      # constraint | procedure | insight | episode
    when: str = ""             # когда применять
    helpful: int = 0
    harmful: int = 0


@dataclass
class Memory:
    records: list = field(default_factory=list)
    counter: int = 0

    def add(self, text, **fields):
        self.counter += 1
        rec = Record(f"r{self.counter}", text, **fields)
        self.records.append(rec)
        return rec

    def get(self, id):
        return next((r for r in self.records if r.id == id), None)

    def drop(self, id):
        self.records = [r for r in self.records if r.id != id]

    def replace_all(self, text):
        """Полная перезапись одним текстом (Dynamic Cheatsheet)."""
        self.records = [Record("r0", text)]

    def text(self):
        return "\n".join(f"[{r.id}] {r.text}" for r in self.records)

    def save(self, path):
        json.dump([asdict(r) for r in self.records], open(path, "w"), ensure_ascii=False, indent=1)
