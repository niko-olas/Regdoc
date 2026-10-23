"""Client degli embedding sul deployment Foundry (Azure OpenAI)."""
from azure.core.credentials import TokenCredential
from azure.identity import get_bearer_token_provider
from openai import AzureOpenAI

# openai è il client che Microsoft documenta per i modelli Azure OpenAI su Foundry.
API_VERSION = "2024-10-21"
# Più testi per richiesta: meno round trip. Il limite del servizio è molto più alto,
# ma batch piccoli tengono ogni richiesta sotto la quota di token al minuto.
BATCH_SIZE = 64


class Embedder:
    def __init__(self, endpoint: str, deployment: str, credential: TokenCredential):
        self._deployment = deployment
        self._client = AzureOpenAI(
            azure_endpoint=endpoint,
            api_version=API_VERSION,
            # Token Entra ID al posto della chiave (disattivata sulla risorsa).
            azure_ad_token_provider=get_bearer_token_provider(credential, "https://cognitiveservices.azure.com/.default"),
            # Il client ritenta da solo su 429 (quota TPM superata) e 5xx, con backoff
            # esponenziale e rispettando l'header Retry-After del servizio.
            max_retries=5,
        )

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for i in range(0, len(texts), BATCH_SIZE):
            response = self._client.embeddings.create(model=self._deployment, input=texts[i:i + BATCH_SIZE])
            vectors.extend(item.embedding for item in sorted(response.data, key=lambda d: d.index))
        return vectors
