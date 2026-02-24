FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir \
    fastapi \
    uvicorn \
    jinja2 \
    requests \
    opentelemetry-api \
    opentelemetry-sdk \
    opentelemetry-exporter-otlp \
    opentelemetry-instrumentation-fastapi \
    opentelemetry-instrumentation-requests

COPY main.py /app/main.py
COPY templates /app/templates

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8002"]
