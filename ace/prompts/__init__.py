"""Все тексты для модели — шаблоны Jinja2 в ace/prompts/ (имя.j2): промпты апстримов (дословно, только
подстановка переведена в Jinja) и строки стенда. Файл — ровно то, что получит модель: завершающий перевод строки
сохраняется, неизвестное поле — ошибка.

    load(name)      шаблон промпта: .fill(поля) -> текст
    text(name)      шаблон, сразу заполненный: промпты без полей и короткие строки
    macros(name)    короткие строки одного места — макросы одного шаблона (описания инструментов, отбивки,
                    разметка): macros("fs").no_file(path=...) -> текст; у строк апстрима источник — в комментарии
                    шаблона
    tool(описание)  инструмент модели: описание, которое она видит, — из шаблона; докстрока функции — для читателя;
                    schema — схема аргументов, если модель должна видеть её как есть (как шлёт апстрим)"""
import jinja2

from ..config import PROMPTS

ENV = jinja2.Environment(loader=jinja2.FileSystemLoader(PROMPTS), keep_trailing_newline=True,
                         undefined=jinja2.StrictUndefined, autoescape=False)


class Template:
    def __init__(self, name):
        self.name = name
        self.template = ENV.get_template(f"{name}.j2")

    def __deepcopy__(self, memo):
        """Шаблон неизменяем: копия ученика (снимок, прогон) делит его с оригиналом."""
        return self

    def fill(self, **values):
        return self.template.render(values)


def load(name):
    return Template(name)


def text(name, /, **values):
    return Template(name).fill(**values)


def macros(name):
    return ENV.get_template(f"{name}.j2").module


def tool(description, schema=None):
    """Декоратор инструмента: pydantic-ai отдаёт модели description (model/agent.py), а не докстроку; со schema —
    и её вместо схемы из сигнатуры."""
    def described(function):
        function.description = description
        if schema is not None:
            function.schema = schema
        return function
    return described
