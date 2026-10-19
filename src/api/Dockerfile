# Contesto di build = src/ (vedi CLAUDE.md), così in F5 potremo copiare anche shared/.
# Build: docker build -t regdoc-api:dev -f src/api/Dockerfile src/
FROM python:3.12-slim

WORKDIR /app

# Prima i requirements: il layer delle dipendenze resta in cache finché
# requirements.txt non cambia, e ACR Tasks / docker build ripartono molto più veloci.
COPY api/requirements.txt api/requirements.txt
RUN pip install --no-cache-dir -r api/requirements.txt

COPY api/ api/

# Utente non root: buona pratica richiesta da molte policy su AKS.
RUN useradd --system --uid 1000 appuser
USER appuser

# App Service ascolta su 80 di default: con una porta diversa va impostata
# l'app setting WEBSITES_PORT=8000. Su AKS/Container Apps è il targetPort.
EXPOSE 8000
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
