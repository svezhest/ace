# апстрим TF-GRPO (youtu-agent) целиком в контейнере: агент исполняет код модели (python_executor, IPython) здесь,
# а не на хосте; версии — как в .venvs/youtu с доставленными ipython, matplotlib (local-python) и math-verify.
# libfaketime — стоящие стенные часы для прогона (run.sh)
FROM python:3.12-slim
COPY requirements.txt /tmp/requirements.txt
RUN apt-get update && apt-get install -y --no-install-recommends libfaketime && rm -rf /var/lib/apt/lists/* \
    && ln -s /usr/lib/*/faketime/libfaketimeMT.so.1 /usr/local/lib/libfaketimeMT.so.1 \
    && pip install --no-cache-dir -r /tmp/requirements.txt && adduser --disabled-password --gecos "" runner
USER runner
