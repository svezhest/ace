FROM python:3.12-slim
# ipython, matplotlib, scipy и pydantic — для инструмента агента TF-GRPO (kernel.py), версии как у апстрима
RUN pip install --no-cache-dir numpy==2.3.3 sympy==1.14.0 scipy==1.16.2 ipython==9.5.0 matplotlib==3.10.6 \
        pydantic==2.12.4 && adduser --disabled-password --gecos "" runner
USER runner
WORKDIR /tmp
