"""Все тексты для модели — шаблоны Jinja2 в ace/prompts/ (имя.j2): промпты апстримов (дословно, только
подстановка переведена в Jinja) и короткие строки стенда. Файл — ровно то, что получит модель:
завершающий перевод строки сохраняется, неизвестное поле — ошибка."""
import jinja2

from ..config import PROMPTS

ENV = jinja2.Environment(loader=jinja2.FileSystemLoader(PROMPTS), keep_trailing_newline=True,
                         undefined=jinja2.StrictUndefined, autoescape=False)


class Prompt:
    def __init__(self, name):
        self.name = name
        self.template = ENV.get_template(f"{name}.j2")

    def fill(self, values=None, /, **more):
        """values: dict полей."""
        return self.template.render({**(values or {}), **more})


def load(name):
    return Prompt(name)


def text(name, /, **values):
    """Шаблон, сразу заполненный: короткие строки и промпты без полей."""
    return Prompt(name).fill(values)
