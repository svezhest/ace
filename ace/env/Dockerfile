FROM python:3.12-slim
RUN pip install --no-cache-dir numpy sympy && adduser --disabled-password --gecos "" runner
USER runner
WORKDIR /tmp
