"""Composizione del prompt con fonti numerate e generazione della risposta con il modello di chat."""
import re

from fielddata.installations import Installation, PastIntervention
from fielddata.search import SimilarIntervention

from api.retrieval import ManualPage

DEFAULT_SYSTEM_PROMPT = """Sei l'assistente tecnico di RegDoc per i tecnici manutentori.
Rispondi in italiano, in modo pratico e ordinato (passi numerati quando servono).
Usa SOLO le fonti fornite: pagine dei manuali [M1], [M2]... e interventi già fatti [I1], [I2]...
Dopo ogni affermazione cita la fonte tra parentesi quadre. Distingui ciò che dice il manuale
da ciò che è esperienza dal campo. Se le fonti non bastano, dillo chiaramente e suggerisci cosa
verificare: non inventare valori, codici di errore o procedure.
Ricorda le norme di sicurezza (stufa spenta e fredda, alimentazione scollegata) quando sono pertinenti."""

MAX_PAGE_CHARS = 1500
# Citazioni tra parentesi quadre, anche multiple: [M3], [M3, M4], [I1; M2].
_BRACKETS = re.compile(r"\[([^\]]+)\]")
_SOURCE_ID = re.compile(r"\b([MI]\d+)\b")


def build_sources(manuals: list[ManualPage], similar: list[SimilarIntervention]) -> list[dict]:
    sources = [
        {"id": f"M{n}", "kind": "manuale", "file_name": m.file_name, "doc_type": m.doc_type, "page": m.page,
         "score": round(m.score, 3), "excerpt": m.text[:300]}
        for n, m in enumerate(manuals, start=1)
    ]
    sources += [
        {"id": f"I{n}", "kind": "intervento", "external_ref": s.external_ref, "performed_on": s.performed_on.isoformat(),
         "model": f"{s.manufacturer} {s.model}", "symptom": s.symptom, "resolution": s.resolution,
         "distance": round(s.distance, 3)}
        for n, s in enumerate(similar, start=1)
    ]
    return sources


def cited_only(sources: list[dict], text: str) -> list[dict]:
    """Le fonti che la risposta cita davvero. Il retrieval porta sempre i k candidati più vicini,
    anche quando non c'entrano (es. interventi di guasto per una domanda sull'orologio): al tecnico
    si mostrano solo quelle usate, con gli stessi identificativi del testo."""
    cited = {sid for group in _BRACKETS.findall(text) for sid in _SOURCE_ID.findall(group)}
    return [s for s in sources if s["id"] in cited]


def build_user_message(question: str, installation: Installation | None, history: list[PastIntervention],
                       manuals: list[ManualPage], similar: list[SimilarIntervention]) -> str:
    parts = []
    if installation:
        attrs = ", ".join(f"{k}={v}" for k, v in installation.attributes.items())
        parts.append(
            f"IMPIANTO: {installation.manufacturer} {installation.model} (matricola {installation.serial_number}, "
            f"installato il {installation.installed_on}, {attrs}) presso {installation.customer}, {installation.city}."
        )
        if history:
            parts.append("STORICO DI QUESTO IMPIANTO (più recenti prima):")
            parts += [f"- {h.performed_on} {h.kind}: {h.symptom or ''} → {h.resolution}" for h in history]
    parts.append("PAGINE DEI MANUALI:")
    parts += [f"[M{n}] {m.file_name}, pagina {m.page}:\n{m.text[:MAX_PAGE_CHARS]}" for n, m in enumerate(manuals, 1)]
    if not manuals:
        parts.append("(nessuna pagina trovata per questo modello)")
    if similar:
        parts.append("INTERVENTI SIMILI GIÀ RISOLTI SU ALTRI IMPIANTI:")
        parts += [
            f"[I{n}] {s.external_ref} del {s.performed_on} su {s.manufacturer} {s.model}. "
            f"Sintomo: {s.symptom}. Intervento: {s.resolution}"
            for n, s in enumerate(similar, 1)
        ]
    parts.append(f"DOMANDA DEL TECNICO: {question}")
    return "\n\n".join(parts)


def generate(client, deployment: str, system_prompt: str, user_message: str) -> tuple[str, dict]:
    response = client.chat.completions.create(
        model=deployment,
        messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_message}],
        # Bassa: per procedure tecniche serve una risposta fedele alle fonti, non creativa.
        temperature=0.2,
        max_tokens=900,
    )
    usage = response.usage
    return response.choices[0].message.content or "", {
        "prompt_tokens": usage.prompt_tokens if usage else None,
        "completion_tokens": usage.completion_tokens if usage else None,
    }
