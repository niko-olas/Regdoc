from api import cache
from ingestion import cache_invalidation


def test_api_e_function_usano_la_stessa_chiave_di_versione():
    assert cache.VERSION_KEY == cache_invalidation.VERSION_KEY


def test_lo_scope_distingue_modello_impianto_e_interventi():
    base = cache.scope_of("stufe-pellet", "extraflame", "karolina", True)
    assert base != cache.scope_of("stufe-pellet", "extraflame", "duchessa", True)
    assert base != cache.scope_of("stufe-pellet", "extraflame", "karolina", False)
    assert base != cache.scope_of("stufe-pellet", "extraflame", "karolina", True, "EXT-KAR-00026")


def test_domande_uguali_a_meno_di_maiuscole_e_spazi():
    assert cache.normalize("  Come pulisco   il BRACIERE? ") == cache.normalize("come pulisco il braciere?")


def test_bump_versions_incrementa_ogni_dominio_una_volta():
    class FakeRedis:
        def __init__(self):
            self.data = {}

        def incr(self, key):
            self.data[key] = self.data.get(key, 0) + 1
            return self.data[key]

    r = FakeRedis()
    assert cache_invalidation.bump_versions({"stufe-pellet"}, client=r) == {"stufe-pellet": 1}
    assert cache_invalidation.bump_versions({"stufe-pellet", "caldaie"}, client=r) == {"caldaie": 1, "stufe-pellet": 2}


def test_vettore_in_float32():
    assert len(cache._to_bytes([0.0] * 1536)) == 1536 * 4
