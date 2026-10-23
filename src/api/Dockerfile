# Contesto di build = src/ (vedi CLAUDE.md): l'immagine copia anche shared/ e fielddata/.
# Build: docker build -t regdoc-api:dev -f src/api/Dockerfile src/
FROM python:3.12-slim

WORKDIR /app

# Prima i requirements: il layer delle dipendenze resta in cache finché
# requirements.txt non cambia, e ACR Tasks / docker build ripartono molto più veloci.
COPY api/requirements.txt api/requirements.txt
RUN pip install --no-cache-dir -r api/requirements.txt

COPY shared/ shared/
COPY fielddata/ fielddata/
COPY api/ api/

# La versione appartiene all'immagine, non alla configurazione: la passa la build
# (az acr build --build-arg APP_VERSION=x.y.z) e coincide con il tag. Così /version
# dice sempre quale immagine sta girando. Un'app setting con lo stesso nome la
# sovrascriverebbe, perché App Service inietta le app settings come env al run.
ARG APP_VERSION=dev
ENV APP_VERSION=$APP_VERSION

# Utente non root: buona pratica richiesta da molte policy su AKS.
RUN useradd --system --uid 1000 appuser
USER appuser

# App Service ascolta su 80 di default: con una porta diversa va impostata
# l'app setting WEBSITES_PORT=8000. Su AKS/Container Apps è il targetPort.
EXPOSE 8000
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
