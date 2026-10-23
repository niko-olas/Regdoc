"""Regole condivise sugli interventi: usate dall'import e, in F4, dall'API."""


def embedding_text(symptom: str | None, resolution: str) -> str:
    """Testo da cui si calcola l'embedding di un intervento.

    Sintomo e soluzione insieme: la ricerca deve trovare un intervento sia descrivendo il problema
    ("allarme sonda fumi") sia l'azione ("sostituita la candeletta"). Lo stesso testo va usato
    all'import e quando si aggiunge un intervento, altrimenti i vettori non sono confrontabili.
    """
    return f"Sintomo: {symptom or 'nessuno (intervento programmato)'}\nIntervento: {resolution}"
