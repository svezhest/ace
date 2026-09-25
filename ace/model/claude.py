"""Агент Claude Agent SDK на модели стенда — агенты MCE апстрима (claude_agent_sdk 0.1.23, CLI 2.1.20 из пакета).

CLI шлёт Anthropic /v1/messages на ANTHROPIC_BASE_URL (config.CLAUDE_BASE_URL) — прокси LiteLLM
(bridge/live/mce/litellm.yaml: любое имя -> chat/completions сервера модели, use_chat_completions_url_for_anthropic_messages
обязателен), тот — на сервер модели (шлюз, запись или воспроизведение). Фоновые вызовы малой модели CLI (разбор
команд Bash, пути файлов из вывода) идут туда же.

Окружение CLI задаётся целиком (env), а не наследуется от процесса стенда: от него зависят инструменты агента
(Bash: python3 и uv из .venv корня, оболочка, HOME) и значит его запросы. Корень (root) — папка над workspace/,
как корень репозитория апстрима: в ней home/, tmp/ и .venv (окружение python апстрима, config.MCE_VENV). У записи
апстрима то же окружение (bridge/live/mce/env.txt)."""
import asyncio
import os
import shutil
from pathlib import Path

from .. import config


def env(root, model_url):
    """Окружение CLI и того, что он запускает; model_url — сервер модели для utils/llm.py агентов (OPENROUTER_*)."""
    root = str(root)
    uv = os.path.dirname(shutil.which("uv") or "/usr/bin/uv")
    return {"HOME": f"{root}/home", "TMPDIR": f"{root}/tmp",
            "PATH": f"{root}/.venv/bin:{uv}:/usr/bin:/bin:/usr/sbin:/sbin", "VIRTUAL_ENV": f"{root}/.venv",
            "SHELL": "/bin/bash", "LANG": "en_US.UTF-8", "UV_NO_SYNC": "1",
            "ANTHROPIC_BASE_URL": config.CLAUDE_BASE_URL, "ANTHROPIC_AUTH_TOKEN": "x", "ANTHROPIC_API_KEY": "",
            "ANTHROPIC_MODEL": config.MODEL, "ANTHROPIC_DEFAULT_HAIKU_MODEL": config.MODEL,
            "ANTHROPIC_SMALL_FAST_MODEL": config.MODEL, "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
            "OPENROUTER_API_KEY": "x", "OPENROUTER_API_BASE": model_url}


def prepare(root):
    """Корень: home/ и tmp/ CLI, .venv — окружение апстрима."""
    root = Path(root)
    for d in ("home", "tmp"):
        (root / d).mkdir(parents=True, exist_ok=True)
    if not (root / ".venv").exists():
        (root / ".venv").symlink_to(config.MCE_VENV)


def session(prompt, options, feedback, attempts, environ):
    """Разговор ClaudeSDKClient, как у агентов MCE: промпт, ответ до конца; feedback() -> None (готово) или текст
    следующего сообщения; до attempts ответов. -> готово ли. CLI запускается с окружением environ целиком."""
    return asyncio.run(_session(prompt, options, feedback, attempts, environ))


async def _session(prompt, options, feedback, attempts, environ):
    from claude_agent_sdk import ClaudeSDKClient
    saved = dict(os.environ)
    os.environ.clear()          # SDK отдаёт CLI os.environ процесса: на время запуска — только environ
    os.environ.update(environ)
    try:
        client = ClaudeSDKClient(options=options)
        await client.connect()
    finally:
        os.environ.clear()
        os.environ.update(saved)
    try:
        await client.query(prompt)
        for attempt in range(attempts):
            async for _ in client.receive_response():
                pass
            note = feedback()
            if note is None:
                return True
            if attempt + 1 >= attempts:
                break
            await client.query(note)
        return False
    finally:
        await client.disconnect()
