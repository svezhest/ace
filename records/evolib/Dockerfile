# апстрим EvoLib целиком в контейнере: код модели (тесты LiveCodeBench) исполняется здесь, а не на хосте.
# requirements.txt — полный список версий: requirements.txt EvoLib, lcb_runner по uv.lock LiveCodeBench (anthropic,
# datasets, huggingface-hub, tqdm), грейдер matharena (loguru, regex, antlr4 4.11, sympy, pyyaml, axiom-axle)
FROM python:3.12.14-slim
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && adduser --disabled-password --gecos "" runner
USER runner
