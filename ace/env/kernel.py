"""Инструмент execute_python_code агента TF-GRPO (youtu-agent: utu/tools/python_executor_toolkit.py,
utu/tools/local_env/python.py; вызов инструмента — FunctionTool openai-agents). Файл исполняется внутри песочницы
(sandbox.Kernel): строка stdin {"arguments": аргументы вызова JSON-строкой} -> строка ответа {"output": текст для
модели}. Один IPython на попытку, как persistent shell апстрима: переменные живут между вызовами.

Аргументы — как _on_invoke_tool openai-agents: json.loads, модель execute_python_code_args (code, timeout = 30),
ошибки — текстом default_tool_error_function. Исполнение — execute_python_code_sync: заголовок с пределом памяти,
вывод stdout / stderr через redirect, картинки matplotlib в файл, результат — dict; модели уходит str(dict).
Предел времени — timeout вызова, как asyncio.wait_for апстрима; после него ядро завершается (у апстрима поток
с ячейкой живёт дальше), следующий вызов начнёт новое."""
import base64
import contextlib
import glob
import io
import json
import os
import re
import sys
import threading
import traceback
import uuid
from datetime import datetime

import matplotlib
import matplotlib.pyplot as plt
from IPython.core.interactiveshell import InteractiveShell
from pydantic import Field, ValidationError, create_model
from traitlets.config.loader import Config

matplotlib.use("Agg")

TOOL = "execute_python_code"
ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")
MAX_MEMORY_GB = 16
CODE_HEADER = f"""
import resource
try:
    memory_limit_bytes = {MAX_MEMORY_GB * 1024 * 1024 * 1024}
    resource.setrlimit(resource.RLIMIT_AS, (memory_limit_bytes, memory_limit_bytes))
except (ValueError, resource.error):
    pass
"""
ARGS = create_model(f"{TOOL}_args", code=(str, Field(..., description="The Python code to execute.")),
                    timeout=(int, Field(default=30, description="The execution timeout in seconds. Defaults to 30.")))


def create_shell():
    InteractiveShell.clear_instance()
    config = Config()
    config.HistoryManager.enabled = False
    config.HistoryManager.hist_file = ":memory:"
    shell = InteractiveShell.instance(config=config)
    if hasattr(shell, "history_manager"):
        shell.history_manager.enabled = False
    return shell


def execute(code, workdir, shell):
    """execute_python_code_sync апстрима с переданным shell."""
    original_dir = os.getcwd()
    try:
        code_clean = code.strip()
        if code_clean.startswith("```python"):
            code_clean = code_clean.split("```python")[1].split("```")[0].strip()
        code_clean = CODE_HEADER + code_clean
        os.makedirs(workdir, exist_ok=True)
        os.chdir(workdir)
        files_before = set(glob.glob("*"))
        if hasattr(shell, "history_manager"):
            shell.history_manager.enabled = False
        output = io.StringIO()
        error_output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error_output):
            shell.run_cell(code_clean)
            if plt.get_fignums():
                img_buffer = io.BytesIO()
                plt.savefig(img_buffer, format="png")
                img_base64 = base64.b64encode(img_buffer.getvalue()).decode("utf-8")
                plt.close()
                image_name = "output_image.png"
                counter = 1
                while os.path.exists(image_name):
                    image_name = f"output_image_{counter}.png"
                    counter += 1
                with open(image_name, "wb") as f:
                    f.write(base64.b64decode(img_base64))
        stdout_result = ANSI_ESCAPE.sub("", output.getvalue())
        stderr_result = ANSI_ESCAPE.sub("", error_output.getvalue())
        new_files = [os.path.join(workdir, f) for f in set(glob.glob("*")) - files_before]
        success = not ("Error" in stderr_result or ("Error" in stdout_result and "Traceback" in stdout_result))
        message = "Code execution completed, no output"
        if stdout_result.strip():
            message = f"Code execution completed\nOutput:\n{stdout_result.strip()}"
        return {"workdir": workdir, "success": success, "message": message, "status": True, "files": new_files,
                "error": stderr_result.strip()}
    except Exception as e:
        return {"workdir": workdir, "success": False,
                "message": f"Code execution failed, error message:\n{str(e)},\nTraceback:{traceback.format_exc()}",
                "status": False, "files": [], "error": str(e)}
    finally:
        os.chdir(original_dir)


def timed_out(timeout):
    return {"success": False, "stdout": "", "stderr": "", "status": False, "output": "", "files": [],
            "error": f"Code execution timed out ({timeout} seconds)"}


def invoke(arguments, workdir, shell):
    """Вызов инструмента -> (текст для модели, успел ли код)."""
    try:
        data = json.loads(arguments) if arguments else {}
    except json.JSONDecodeError as e:
        return f"An error occurred while parsing tool arguments. Please try again with valid JSON. Error: {e}", True
    failed = "An error occurred while running the tool. Please try again. Error: "
    try:
        args = ARGS(**data) if data else ARGS()
    except ValidationError as e:
        return f"{failed}Invalid JSON input for tool {TOOL}: {e}", True
    except Exception as e:      # не словарь: ** падает
        return f"{failed}{e}", True
    box = []
    worker = threading.Thread(target=lambda: box.append(execute(args.code, workdir, shell)), daemon=True)
    worker.start()
    worker.join(args.timeout)
    if not box:
        return str(timed_out(args.timeout)), False
    return str(box[0]), True


def main():
    # протокол — на копии stdout; сам stdout процесса (вывод мимо redirect, подпроцессы) — в stderr
    proto = os.fdopen(os.dup(1), "w")
    os.dup2(2, 1)
    workdir = f"/tmp/utu/python_executor/{datetime.now().strftime('%Y%m%d_%H%M%S')}_{str(uuid.uuid4())[:8]}"
    os.makedirs(workdir, exist_ok=True)
    shell = create_shell()
    for line in sys.stdin:
        output, alive = invoke(json.loads(line)["arguments"], workdir, shell)
        proto.write(json.dumps({"output": output}) + "\n")
        proto.flush()
        if not alive:
            os._exit(0)


if __name__ == "__main__":
    main()
