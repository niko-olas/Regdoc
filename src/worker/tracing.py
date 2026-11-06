"""Contesto della traccia tra i componenti: dal messaggio di Service Bus al worker, dal worker al manifest.

Logica pura sopra l'API di OpenTelemetry: si testa senza Application Insights.
"""
from opentelemetry import propagate
from opentelemetry.context import Context


def _text(value) -> str | None:
    return value.decode("ascii") if isinstance(value, bytes) else value


def message_carrier(application_properties: dict | None) -> dict[str, str]:
    """Header W3C dalle proprietà applicative del messaggio.

    Quando la traccia è attiva, l'SDK di Service Bus scrive il contesto in `traceparent` (e, per
    compatibilità, in `Diagnostic-Id`); in ricezione le chiavi arrivano come bytes.
    """
    props = {_text(k): v for k, v in (application_properties or {}).items()}
    carrier = {}
    traceparent = _text(props.get("traceparent") or props.get("Diagnostic-Id"))
    if traceparent:
        carrier["traceparent"] = traceparent
    tracestate = _text(props.get("tracestate"))
    if tracestate:
        carrier["tracestate"] = tracestate
    return carrier


def context_from_message(application_properties: dict | None) -> Context:
    """Contesto da usare come padre dello span di elaborazione (vuoto se il messaggio non ne porta)."""
    return propagate.extract(message_carrier(application_properties))


def current_traceparent() -> str | None:
    """`traceparent` dello span corrente, da salvare dove gli header non arrivano (il manifest)."""
    carrier: dict[str, str] = {}
    propagate.inject(carrier)
    return carrier.get("traceparent")
