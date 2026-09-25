# апстрим TF-GRPO (youtu-agent) целиком в контейнере: агент исполняет код модели (python_executor, IPython) здесь,
# а не на хосте; версии — как в .venvs/youtu с доставленными ipython, matplotlib (local-python) и math-verify
FROM python:3.12-slim
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && adduser --disabled-password --gecos "" runner
USER runner
