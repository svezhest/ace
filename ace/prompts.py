"""Промпты методов лежат файлами в ace/methods/prompts/ и берутся из апстримов как есть.
У каждого свой синтаксис подстановки, его и сохраняем:
    format      {name}                      SCOPE, MCE, EvoLib, ACE-куратор
    positional  {} по порядку               ACE-рефлектор
    brackets    [[NAME]]                    Dynamic Cheatsheet
    jinja       {{ name }}                  TF-GRPO (yaml с парами _SP / _UP)"""
from dataclasses import dataclass

from .config import PROMPTS as DIR


@dataclass
class Prompt:
    text: str
    style: str = "format"

    def fill(self, values):
        """values: dict полей, для positional — список."""
        if self.style == "positional":
            return self.text.format(*values)
        if self.style == "brackets":
            s = self.text
            for k, v in values.items():
                s = s.replace(f"[[{k}]]", str(v))
            return s
        if self.style == "jinja":
            import jinja2
            return jinja2.Template(self.text).render(**values)
        return self.text.format(**values)


def load(name, style="format"):
    return Prompt((DIR / name).read_text(), style)


def load_yaml(name):
    """Все промпты yaml-файла, синтаксис jinja."""
    import yaml
    return {k: Prompt(v, "jinja") for k, v in yaml.safe_load((DIR / name).read_text()).items()}
