"""Impianti e storico interventi: il contesto di partenza di ogni domanda del tecnico."""
from dataclasses import dataclass
from datetime import date

import psycopg


@dataclass
class Installation:
    serial_number: str
    domain: str
    manufacturer: str
    model: str
    installed_on: date | None
    customer: str
    city: str | None
    attributes: dict


@dataclass
class PastIntervention:
    external_ref: str
    performed_on: date
    kind: str
    symptom: str | None
    resolution: str


def get_installation(conn: psycopg.Connection, serial_number: str) -> Installation | None:
    row = conn.execute(
        """
        SELECT i.serial_number, i.domain, i.manufacturer, i.model, i.installed_on, c.name, c.city, i.attributes
        FROM installations i JOIN customers c ON c.id = i.customer_id
        WHERE i.serial_number = %s
        """,
        (serial_number,),
    ).fetchone()
    return Installation(*row) if row else None


def list_installations(conn: psycopg.Connection, limit: int = 200) -> list[Installation]:
    rows = conn.execute(
        """
        SELECT i.serial_number, i.domain, i.manufacturer, i.model, i.installed_on, c.name, c.city, i.attributes
        FROM installations i JOIN customers c ON c.id = i.customer_id
        ORDER BY c.name, i.serial_number
        LIMIT %s
        """,
        (limit,),
    ).fetchall()
    return [Installation(*r) for r in rows]


def history(conn: psycopg.Connection, serial_number: str, limit: int = 5) -> list[PastIntervention]:
    # Usa ix_interventions_installation (installation_id, performed_on DESC): niente sort.
    rows = conn.execute(
        """
        SELECT iv.external_ref, iv.performed_on, iv.kind, iv.symptom, iv.resolution
        FROM interventions iv JOIN installations i ON i.id = iv.installation_id
        WHERE i.serial_number = %s
        ORDER BY iv.performed_on DESC
        LIMIT %s
        """,
        (serial_number, limit),
    ).fetchall()
    return [PastIntervention(*r) for r in rows]
