"""Errori permanenti: riprovare non cambierebbe l'esito, il messaggio va in dead-letter."""


class PermanentError(Exception):
    """Base degli errori che portano a un dead-letter esplicito."""

    reason = "PermanentError"


class InvalidMessage(PermanentError):
    """Il corpo del messaggio non è quello prodotto dalla Function di ingestion."""

    reason = "InvalidMessage"


class InvalidDocument(PermanentError):
    """Il blob non esiste più, non è un PDF leggibile o non contiene testo estraibile."""

    reason = "InvalidDocument"
