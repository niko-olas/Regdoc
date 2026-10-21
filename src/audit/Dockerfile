# Contesto di build = src/ (vedi CLAUDE.md).
# Build: docker build -t regdoc-audit:dev -f src/audit/Dockerfile src/
FROM python:3.12-slim

WORKDIR /app

COPY audit/requirements.txt audit/requirements.txt
RUN pip install --no-cache-dir -r audit/requirements.txt

COPY audit/ audit/

ARG APP_VERSION=dev
ENV APP_VERSION=$APP_VERSION
# Log subito su stdout, senza buffer: Container Apps li raccoglie da lì.
ENV PYTHONUNBUFFERED=1

RUN useradd --system --uid 1000 appuser
USER appuser

# Nessuna porta: è un consumer, non riceve traffico HTTP.
CMD ["python", "-m", "audit.main"]
