import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts" / "db"))

from fielddata.interventions import embedding_text  # noqa: E402
from sample_data import TODAY, generate  # noqa: E402


def test_dati_deterministici():
    assert generate() == generate()


def test_integrita_referenziale_e_chiavi_uniche():
    customers, installations, interventions = generate()
    codes = {c.code for c in customers}
    serials = {i.serial_number for i in installations}
    assert all(i.customer_code in codes for i in installations)
    assert all(i.serial_number in serials for i in interventions)
    assert len(serials) == len(installations)
    assert len({i.external_ref for i in interventions}) == len(interventions)


def test_ogni_impianto_ha_la_sua_installazione_e_nessuna_data_futura():
    _, installations, interventions = generate()
    installed = {i.serial_number for i in interventions if i.kind == "installazione"}
    assert installed == {i.serial_number for i in installations}
    assert all(i.performed_on < TODAY for i in interventions)


def test_ci_sono_guasti_sulla_karolina():
    _, installations, interventions = generate()
    karolina = {i.serial_number for i in installations if i.model == "karolina"}
    assert any(i.kind == "guasto" and i.serial_number in karolina for i in interventions)


def test_embedding_text_include_sintomo_e_intervento():
    text = embedding_text("Allarme sonda fumi", "Sostituita la sonda")
    assert "Allarme sonda fumi" in text and "Sostituita la sonda" in text
    assert "programmato" in embedding_text(None, "Manutenzione annuale")


def test_build_query_aggiunge_solo_i_filtri_valorizzati():
    from fielddata.search import build_query

    sql, params = build_query([0.0] * 3, domain="stufe-pellet")
    assert "i.model = " not in sql and "i.manufacturer = " not in sql
    sql, params = build_query([0.0] * 3, domain="stufe-pellet", model="karolina", k=3)
    assert "i.model = %(model)s" in sql and params["model"] == "karolina" and params["k"] == 3
