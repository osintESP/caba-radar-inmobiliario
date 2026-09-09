from ingest.keywords import extract_tags


def test_extracts_multiple_known_phrases():
    texto = "PH de 3 ambientes con quincho y terraza. Apto crédito. Placard empotrado. Sin expensas."
    tags = extract_tags(texto)
    assert "apto_credito" in tags
    assert "quincho" in tags
    assert "terraza" in tags
    assert "placard" in tags
    assert "sin_expensas" in tags


def test_case_insensitive():
    assert "apto_credito" in extract_tags("APTO CREDITO YA")
    assert "apto_credito" in extract_tags("apto crédito")


def test_no_matches_returns_empty_list():
    assert extract_tags("un texto sin ninguna palabra clave conocida") == []


def test_none_or_empty_text_returns_empty_list():
    assert extract_tags(None) == []
    assert extract_tags("") == []


def test_negation_prevents_false_positive_tag():
    """Regresión: encontrado en el primer aviso real probado — "NO APTO
    CREDITO!" se tageaba como apto_credito, justo lo opuesto."""
    assert "apto_credito" not in extract_tags("Luminoso 3 ambientes. NO APTO CREDITO! A estrenar.")
    assert "pileta" not in extract_tags("El edificio no tiene pileta ni sum.")
    assert "cochera" not in extract_tags("Sin cochera, apto para auto chico en la calle.")


def test_negation_does_not_suppress_unrelated_earlier_tag_in_same_text():
    tags = extract_tags("Apto crédito. El depto no tiene pileta.")
    assert "apto_credito" in tags
    assert "pileta" not in tags


def test_sin_expensas_tag_still_works_despite_negation_guard():
    # El propio patron de sin_expensas empieza con "sin"/"no" — no debe
    # anularse a si mismo.
    assert "sin_expensas" in extract_tags("Edificio de pocas unidades, sin expensas.")
    assert "sin_expensas" in extract_tags("No tiene expensas, solo gastos comunes.")


def test_does_not_duplicate_tag_for_multiple_pattern_hits():
    # "apto_credito" tiene dos patrones (apto credito, apto bancario); si
    # el texto matchea ambos no debe aparecer dos veces.
    texto = "apto credito y tambien apto bancario"
    tags = extract_tags(texto)
    assert tags.count("apto_credito") == 1
