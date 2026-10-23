"""La risposta a una domanda del tecnico: impianto → cache → manuali + interventi simili → modello di chat."""
import logging
import time

from opentelemetry import trace

from api import answer, cache
from api.retrieval import search_manuals
from api.services import FLAG_INTERVENTIONS, FLAG_SEMANTIC_CACHE, Services
from fielddata.installations import get_installation, history
from fielddata.search import similar_interventions

log = logging.getLogger("regdoc.api")
tracer = trace.get_tracer("regdoc.api")


# Distanza coseno massima di un intervento "simile". Misurata sui dati di esempio: i guasti pertinenti
# stanno sotto 0,40, le domande estranee (orologio, pulizia, pellet) sopra 0,45.
INTERVENTIONS_MAX_DISTANCE = 0.42


class InstallationNotFound(LookupError):
    pass


class _Stopwatch:
    """Tempi di ogni fase, restituiti al client: dicono subito dove va il tempo di una risposta."""

    def __init__(self):
        self.started = time.perf_counter()
        self.laps: dict[str, float] = {}
        self._t0 = self.started

    def lap(self, name: str) -> None:
        now = time.perf_counter()
        self.laps[name] = round((now - self._t0) * 1000, 1)
        self._t0 = now

    def total(self) -> dict[str, float]:
        return {**self.laps, "totale": round((time.perf_counter() - self.started) * 1000, 1)}


def ask(svc: Services, question: str, *, serial_number: str | None, domain: str,
        manufacturer: str | None, model: str | None) -> dict:
    clock = _Stopwatch()
    svc.config.refresh()
    use_interventions = svc.config.is_enabled(FLAG_INTERVENTIONS)
    use_semantic_cache = svc.config.is_enabled(FLAG_SEMANTIC_CACHE)

    # 1. Impianto: da PostgreSQL ricava dominio, produttore e modello, che filtrano tutto il resto.
    installation, past = None, []
    if serial_number:
        with svc.pool.connection() as conn:
            installation = get_installation(conn, serial_number)
            if installation is None:
                raise InstallationNotFound(serial_number)
            past = history(conn, serial_number)
        domain, manufacturer, model = installation.domain, installation.manufacturer, installation.model
    clock.lap("impianto")

    # 2. Cache esatta: stessa domanda, stesso ambito, stessa versione dei manuali del dominio.
    scope = cache.scope_of(domain, manufacturer, model, use_interventions, serial_number)
    ver = 0
    if svc.cache:
        ver = _safely(lambda: svc.cache.version(domain), "lettura della versione") or 0
        hit = _safely(lambda: svc.cache.get_exact(domain, ver, scope, question), "lettura")
        clock.lap("cache")
        if hit:
            return {**hit, "cache": "exact", "timings_ms": clock.total()}

    # 3. Embedding della domanda: serve sia alla cache semantica sia alla ricerca.
    vector = svc.embedder.embed([question])[0]
    clock.lap("embedding")

    if svc.cache and use_semantic_cache:
        semantic = _safely(lambda: svc.cache.get_semantic(ver, scope, vector), "ricerca semantica")
        clock.lap("cache_semantica")
        if semantic:
            response, distance = semantic
            return {**response, "cache": "semantic", "cache_distance": round(distance, 4), "timings_ms": clock.total()}

    # 4. Manuali del modello su Cosmos DB.
    with tracer.start_as_current_span("rag.search_manuals") as span:
        manuals, ru = search_manuals(svc.chunks, vector, domain=domain, manufacturer=manufacturer, model=model)
        span.set_attribute("regdoc.cosmos.ru", ru)
        span.set_attribute("regdoc.results", len(manuals))
    clock.lap("manuali")

    # 5. Interventi simili su PostgreSQL (feature flag): stesso modello, solo guasti.
    similar = []
    if use_interventions:
        with tracer.start_as_current_span("rag.similar_interventions"), svc.pool.connection() as conn:
            candidates = similar_interventions(conn, vector, domain=domain, manufacturer=manufacturer, model=model, k=4)
        # La ricerca restituisce sempre i 4 più vicini, anche se lontani: oltre la soglia non sono
        # "guasti simili" e nel prompt sarebbero solo rumore. Soglia in App Configuration, tarata sui dati.
        max_distance = float(svc.config.get("Interventions:MaxDistance", str(INTERVENTIONS_MAX_DISTANCE)))
        similar = [s for s in candidates if s.distance <= max_distance]
        clock.lap("interventi")

    # 6. Risposta del modello di chat, con le fonti numerate.
    system_prompt = svc.config.get(f"Prompt:{domain}", answer.DEFAULT_SYSTEM_PROMPT)
    user_message = answer.build_user_message(question, installation, past, manuals, similar)
    with tracer.start_as_current_span("rag.generate") as span:
        text, usage = answer.generate(svc.chat, svc.chat_deployment, system_prompt, user_message)
        span.set_attribute("regdoc.prompt_tokens", usage["prompt_tokens"] or 0)
    clock.lap("generazione")

    response = {
        "answer": text,
        "sources": answer.cited_only(answer.build_sources(manuals, similar), text),
        "installation": installation.__dict__ if installation else None,
        "scope": {"domain": domain, "manufacturer": manufacturer, "model": model},
        "flags": {FLAG_INTERVENTIONS: use_interventions, FLAG_SEMANTIC_CACHE: use_semantic_cache},
        "usage": {**usage, "cosmos_ru": ru},
    }
    if svc.cache:
        _safely(lambda: svc.cache.store(domain, ver, scope, question, vector, response), "scrittura")
    timings = clock.total()
    log.info("Risposta generata per %s/%s/%s in %.0f ms", domain, manufacturer, model, timings["totale"])
    return {**response, "cache": "miss", "timings_ms": timings}


def _safely(operation, what: str):
    """La cache è un'ottimizzazione: se Redis non risponde si prosegue senza, mai un errore al tecnico."""
    try:
        return operation()
    except Exception:  # noqa: BLE001
        log.warning("Cache: %s fallita", what, exc_info=True)
        return None
