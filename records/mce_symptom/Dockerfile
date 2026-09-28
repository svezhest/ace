# апстрим MCE c4b7a7c (контекст сборки — git archive в up/) с окружением по README: uv sync по uv.lock апстрима
# (хеши сверяются), проект editable в .venv корня; ROOT — тот же путь, что входит в промпты агентов.
# /opt/litellm — LiteLLM для агентов Claude CLI: python 3.12.8 и версии litellm.req.txt, как $UPSTREAMS/.venvs/litellm.
FROM python:3.11.11-slim-bookworm@sha256:081075da77b2b55c23c088251026fb69a7b2bf92471e491ff5fd75c192fd38e5
COPY --from=ghcr.io/astral-sh/uv:0.5.9@sha256:ba36ea627a75e2a879b7f36efe01db5a24038f8d577bd7214a6c99d5d4f4b20c /uv /uvx /usr/local/bin/
COPY litellm.req.txt /opt/
RUN UV_PYTHON_DOWNLOADS=automatic UV_PYTHON_INSTALL_DIR=/opt/python uv venv -p 3.12.8 /opt/litellm \
    && uv pip install --no-cache -p /opt/litellm -r /opt/litellm.req.txt \
    && adduser --disabled-password --gecos "" runner
COPY --chown=runner up/ /private/tmp/mce-symptom/
USER runner
WORKDIR /private/tmp/mce-symptom
# кэш uv — в home агентов (HOME из env.txt): uv run агента пересобирает editable-проект из кэша без сети
RUN mkdir home tmp && HOME=/private/tmp/mce-symptom/home UV_PYTHON_DOWNLOADS=never uv sync --frozen
