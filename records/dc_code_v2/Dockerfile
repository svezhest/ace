# апстрим DC целиком в контейнере: код модели исполняется здесь, а не на хосте; версии — как в .venvs/light
FROM python:3.11-slim
RUN pip install --no-cache-dir datasets==5.0.1 numpy==2.4.6 openai==3.19.2 pandas==3.0.6 pyarrow==25.0.1 \
        python-dotenv==1.2.3 scikit-learn==1.9.1 tiktoken==0.14.0 typed-argument-parser==1.12.0 \
    && adduser --disabled-password --gecos "" runner
USER runner
