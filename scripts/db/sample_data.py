"""Dati di esempio dal campo: clienti, impianti e interventi plausibili per stufe a pellet.

Deterministici (seed fisso): rieseguire l'import produce gli stessi dati, e l'upsert li aggiorna
invece di duplicarli. Nomi e tecnici sono inventati: nessun dato personale reale.
"""
import random
from dataclasses import dataclass, field
from datetime import date, timedelta

SEED = 42
TODAY = date(2026, 10, 1)


@dataclass
class Customer:
    code: str
    name: str
    city: str


@dataclass
class Installation:
    serial_number: str
    customer_code: str
    domain: str
    manufacturer: str
    model: str
    installed_on: date
    attributes: dict = field(default_factory=dict)


@dataclass
class Intervention:
    external_ref: str
    serial_number: str
    performed_on: date
    kind: str
    technician: str
    symptom: str | None
    resolution: str
    duration_minutes: int


# (produttore, modello, potenza kW, peso nella scelta). Karolina più frequente: ha il manuale indicizzato.
MODELS = [
    ("extraflame", "karolina", 8, 4),
    ("extraflame", "duchessa", 9, 2),
    ("edilkamin", "blade-h", 9, 3),
    ("edilkamin", "tally", 7, 2),
    ("mcz", "ego", 6, 2),
    ("palazzetti", "ecofire-ginger", 8, 1),
]

SURNAMES = ["Bianchi", "Rossi", "Ferrari", "Esposito", "Romano", "Colombo", "Ricci", "Marino", "Greco", "Bruno",
            "Gallo", "Conti", "De Luca", "Mancini", "Costa", "Giordano", "Rizzo", "Lombardi", "Moretti", "Barbieri"]
CITIES = ["Trento", "Rovereto", "Bolzano", "Belluno", "Feltre", "Sondrio", "Aosta", "Cuneo", "Udine", "Pordenone"]
TECHNICIANS = ["TEC-01", "TEC-02", "TEC-03", "TEC-04", "TEC-05"]

# Guasti tipici: (sintomi possibili, soluzioni possibili, durata min-max in minuti, modelli più colpiti).
FAULTS = [
    (["La stufa non si accende, sul display compare 'Mancata accensione'.",
      "Dopo il caricamento del pellet la stufa va in allarme di mancata accensione."],
     ["Braciere incrostato: rimossi i residui e liberati i fori dell'aria comburente. Candeletta verificata (resistenza ok). Accensione regolare.",
      "Candeletta guasta (resistenza interrotta): sostituita. Test di accensione superato."],
     (40, 90), []),
    (["Allarme 'Sonda fumi' durante il funzionamento, la stufa va in spegnimento.",
      "Errore temperatura fumi, la stufa si spegne dopo circa mezz'ora."],
     ["Connettore della sonda fumi ossidato: pulito e serrato, verificata la lettura della temperatura. Nessun nuovo allarme.",
      "Sonda fumi guasta (lettura fuori scala): sostituita e verificato il funzionamento a pieno regime."],
     (45, 100), ["karolina", "duchessa"]),
    (["Allarme pressostato: depressione insufficiente in camera di combustione.",
      "La stufa va in blocco con errore di depressione appena aumenta la potenza."],
     ["Canna fumaria parzialmente ostruita: pulizia completa del condotto fumi e del raccordo a T. Depressione tornata nei valori di targa.",
      "Tubicino del pressostato staccato dal raccordo: ricollegato e fissato con fascetta."],
     (60, 150), ["blade-h", "tally"]),
    (["La fiamma si spegne dopo pochi minuti, nel braciere arriva poco pellet.",
      "Rumore di sfregamento dal serbatoio e alimentazione del pellet irregolare."],
     ["Coclea bloccata da pellet sbriciolato e segatura sul fondo del serbatoio: svuotato e pulito il serbatoio, consigliato pellet certificato ENplus A1.",
      "Motoriduttore della coclea lento e rumoroso: sostituito."],
     (50, 120), []),
    (["Il vetro della porta si annerisce in poche ore, fiamma bassa e scura."],
     ["Combustione con poca aria: aumentata la velocità dell'estrattore fumi nella ricetta di combustione e sostituita la guarnizione della porta, ormai indurita."],
     (40, 80), []),
    (["Rumore metallico continuo dal ventilatore ambiente."],
     ["Ventilatore ambiente sporco e sbilanciato: smontato e pulito, rumore eliminato.",
      "Cuscinetti del ventilatore ambiente usurati: sostituito il ventilatore."],
     (40, 90), ["ego", "blade-h"]),
    (["Allarme termostato di sicurezza del serbatoio, stufa bloccata."],
     ["Scambiatore molto sporco e ventilazione insufficiente: pulizia dello scambiatore e riarmo manuale del termostato di sicurezza."],
     (60, 120), []),
    (["Display spento, la stufa non risponde ai comandi."],
     ["Fusibile della scheda elettronica bruciato dopo un temporale: sostituito il fusibile, consigliato uno scaricatore di sovratensioni."],
     (30, 60), []),
    (["Odore di fumo in ambiente all'accensione."],
     ["Guarnizione del cassetto cenere deteriorata: sostituita. Ripristinata la tenuta del raccordo fumi con sigillante per alte temperature."],
     (45, 90), []),
    (["Accensioni lente e molta cenere da quando il cliente usa un nuovo lotto di pellet."],
     ["Pellet umido (conservato in garage): consigliato lo stoccaggio in luogo asciutto. Puliti braciere e cassetto cenere."],
     (30, 50), []),
]

MAINTENANCE = [
    "Manutenzione annuale: pulizia di braciere, scambiatore, condotto fumi ed estrattore. Verificate guarnizione della porta e depressione in camera di combustione.",
    "Manutenzione annuale: pulizia completa e controllo della candeletta. Sostituita la guarnizione del vetro. Analisi fumi nei limiti.",
    "Manutenzione annuale: pulizia del giro fumi e del ventilatore estrattore, controllo della coclea. Nessuna anomalia.",
]
INSTALLATION = ("Installazione e collaudo: allacciamento alla canna fumaria con raccordo a T e tappo di ispezione, "
                "verifica del tiraggio, prima accensione e istruzioni d'uso al cliente.")


def _random_day(rng: random.Random, start: date, end: date) -> date:
    return start + timedelta(days=rng.randint(0, max((end - start).days, 0)))


def generate() -> tuple[list[Customer], list[Installation], list[Intervention]]:
    rng = random.Random(SEED)
    customers = [
        Customer(code=f"C{n:03d}", name=f"Famiglia {SURNAMES[n - 1]}", city=rng.choice(CITIES))
        for n in range(1, len(SURNAMES) + 1)
    ]

    installations: list[Installation] = []
    for customer in customers:
        for _ in range(rng.choice([1, 1, 2, 2, 3])):
            manufacturer, model, kw, _w = rng.choices(MODELS, weights=[m[3] for m in MODELS])[0]
            installations.append(Installation(
                serial_number=f"{manufacturer[:3].upper()}-{model[:3].upper()}-{len(installations) + 1:05d}",
                customer_code=customer.code,
                domain="stufe-pellet",
                manufacturer=manufacturer,
                model=model,
                installed_on=_random_day(rng, date(2019, 9, 1), date(2024, 11, 30)),
                attributes={"potenza_kw": str(kw)},
            ))

    interventions: list[Intervention] = []

    def add(inst: Installation, day: date, kind: str, symptom: str | None, resolution: str, minutes: int) -> None:
        interventions.append(Intervention(
            external_ref=f"INT-{len(interventions) + 1:05d}",
            serial_number=inst.serial_number,
            performed_on=day,
            kind=kind,
            technician=rng.choice(TECHNICIANS),
            symptom=symptom,
            resolution=resolution,
            duration_minutes=minutes,
        ))

    for inst in installations:
        add(inst, inst.installed_on, "installazione", None, INSTALLATION, rng.randint(150, 240))

        # Una manutenzione ogni autunno dopo l'installazione.
        for year in range(inst.installed_on.year + 1, TODAY.year):
            add(inst, _random_day(rng, date(year, 9, 1), date(year, 11, 15)), "manutenzione",
                None, rng.choice(MAINTENANCE), rng.randint(60, 120))

        # Da 0 a 3 guasti nella stagione di riscaldamento; i modelli "colpiti" ne hanno di più.
        for _ in range(rng.choice([0, 1, 1, 2, 3])):
            weights = [3 if inst.model in models else 1 for *_x, models in FAULTS]
            symptoms, resolutions, (lo, hi), _models = rng.choices(FAULTS, weights=weights)[0]
            year = rng.randint(inst.installed_on.year, TODAY.year - 1)
            day = _random_day(rng, max(date(year, 10, 15), inst.installed_on + timedelta(days=30)), date(year + 1, 3, 15))
            if day < TODAY:
                add(inst, day, "guasto", rng.choice(symptoms), rng.choice(resolutions), rng.randint(lo, hi))

    return customers, installations, interventions
