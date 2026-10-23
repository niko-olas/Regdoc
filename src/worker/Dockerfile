# Contesto di build = src/ (vedi CLAUDE.md): così l'immagine include anche shared/.
# Build: docker build -t regdoc-worker:dev -f src/worker/Dockerfile src/
FROM python:3.12-slim

WORKDIR /app

COPY worker/requirements.txt worker/requirements.txt
RUN pip install --no-cache-dir -r worker/requirements.txt

COPY shared/ shared/
COPY worker/ worker/

ARG APP_VERSION=dev
ENV APP_VERSION=$APP_VERSION
ENV PYTHONUNBUFFERED=1

RUN useradd --system --uid 1000 appuser
USER appuser

# Consumer di Service Bus: nessuna porta esposta.
CMD ["python", "-m", "worker.main"]
