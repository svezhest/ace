"""Сценарий записи SCOPE с оптимизатором памяти.

Тест 1 examples/test_scope_deep.py (json_agent, та же роль, задача, промпт и настройки оптимизатора), только вывод
агента и ошибка — не один придуманный документ, а каждый fail*.json набора JSON_checker (json.org), который
json.loads отвергает. Одна задача — один SCOPEOptimizer на общем exp_path, промпт — базовый плюс стратегические
правила из памяти, как в Quick Start README. Правила одного агента копятся, и когда в домене их больше 10,
StrategicMemoryStore вызывает MemoryOptimizer. Набор проходится заново (до трёх раз), пока оптимизатор не сработает;
проход, в котором он сработал, — последний.

Запуск из корня апстрима с PYTHONPATH=. и аргументами примера: --provider openai --model M --api-key K --base-url U
"""
import asyncio
import json
import logging
import os
import tempfile
import zipfile

from examples.test_scope_deep import create_model, parse_args
from scope import SCOPEOptimizer

PASSES = 3
SUITE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "json_checker.zip")


def failures():
    """(имя, документ, текст ошибки) в порядке номеров fail*.json. fail1 и fail18 json.loads принимает —
    это не ошибка агента, их нет."""
    with zipfile.ZipFile(SUITE) as z:
        names = [n for n in z.namelist() if os.path.basename(n).startswith("fail")]
        names.sort(key=lambda n: int(os.path.basename(n)[4:-5]))
        for name in names:
            doc = z.read(name).decode()
            try:
                json.loads(doc)
            except json.JSONDecodeError as e:
                yield os.path.basename(name)[:-5], doc, f"JSONDecodeError: {e}"


class Triggered(logging.Handler):
    """Считает срабатывания оптимизатора по журналу StrategicMemoryStore."""
    count = 0

    def emit(self, record):
        self.count += record.getMessage().startswith("[RuleOptimization] Triggered")


async def main():
    args = parse_args()
    model = create_model(args)
    # собственный журнал SCOPE (срабатывание оптимизатора и его шаги) — в вывод
    logging.basicConfig(format="%(name)s: %(message)s")
    logging.getLogger("scope").setLevel(logging.INFO)
    triggered = Triggered()
    logging.getLogger("scope.strategic_store").addHandler(triggered)

    with tempfile.TemporaryDirectory() as tmpdir:
        for k in range(1, PASSES + 1):
            for name, doc, error in failures():
                task_id = f"{name}.{k}"
                optimizer = SCOPEOptimizer(
                    synthesizer_model=model,
                    exp_path=tmpdir,
                    auto_accept_threshold="low",
                )
                prompt = "You are a JSON processing agent." + optimizer.get_strategic_rules_for_agent("json_agent")
                result = await optimizer.on_step_complete(
                    agent_name="json_agent",
                    agent_role="An agent that processes JSON data",
                    task="Parse and validate user input",
                    model_output=doc,
                    error=Exception(error),
                    current_system_prompt=prompt,
                    task_id=task_id,
                )
                print(f"{task_id}: {result[1] if result else 'no guideline'}", flush=True)
            if triggered.count:
                break

        print(f"\nOPTIMIZER TRIGGERED: {triggered.count}")
        # итог — память в конце: каталог временный и удаляется
        path = os.path.join(tmpdir, "strategic_memory", "global_rules.json")
        print("\nSTRATEGIC MEMORY\n" + (open(path).read() if os.path.exists(path) else "{}"))


if __name__ == "__main__":
    asyncio.run(main())
