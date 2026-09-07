import pandas as pd
import pytest

from analysis.valuation import audit_property

ADYACENTES = {
    "Monte Castro": ["Velez Sarsfield", "Floresta"],
    "Velez Sarsfield": ["Monte Castro"],
}


def _comp(portal_id, barrio, usd_m2, m2_cubiertos=72.0, ambientes=3, tipo="departamento", condicion="usado"):
    return {
        "portal_id": portal_id,
        "barrio": barrio,
        "tipo": tipo,
        "condicion": condicion,
        "m2_cubiertos": m2_cubiertos,
        "ambientes": ambientes,
        "usd_m2": usd_m2,
    }


def _make_df(rows):
    return pd.DataFrame(rows)


def test_insufficient_in_barrio_expands_to_adyacentes():
    # 5 en Monte Castro, 30 mas en Velez Sarsfield (adyacente) -> deberia expandir y dar veredicto
    rows = [_comp(f"MC{i}", "Monte Castro", 1800 + i) for i in range(5)]
    rows += [_comp(f"VS{i}", "Velez Sarsfield", 1700 + i) for i in range(30)]
    df = _make_df(rows)

    result = audit_property(df, "Monte Castro", "departamento", 3, 72.0, ADYACENTES)

    assert result.veredicto == "ok"
    assert result.scope == "barrio+adyacentes"
    assert result.n_comparables == 35


def test_still_insufficient_returns_no_verdict():
    rows = [_comp(f"MC{i}", "Monte Castro", 1800 + i) for i in range(5)]
    rows += [_comp(f"VS{i}", "Velez Sarsfield", 1700 + i) for i in range(10)]  # 15 total, sigue por debajo de 30
    df = _make_df(rows)

    result = audit_property(df, "Monte Castro", "departamento", 3, 72.0, ADYACENTES)

    assert result.veredicto == "insuficiente"
    assert result.scope == "insuficiente"
    assert result.usd_m2_mediana is None
    assert result.n_comparables == 15


def test_enough_comparables_in_barrio_alone_does_not_expand():
    rows = [_comp(f"MC{i}", "Monte Castro", 1500 + i * 10) for i in range(30)]
    df = _make_df(rows)

    result = audit_property(df, "Monte Castro", "departamento", 3, 72.0, ADYACENTES)

    assert result.veredicto == "ok"
    assert result.scope == "barrio"
    assert result.n_comparables == 30


def test_m2_tolerance_excludes_far_off_sizes():
    # +-15% de 72 = [61.2, 82.8]. 100m2 queda afuera.
    rows = [_comp(f"MC{i}", "Monte Castro", 1800, m2_cubiertos=72.0) for i in range(30)]
    rows += [_comp(f"MC-big-{i}", "Monte Castro", 900, m2_cubiertos=150.0) for i in range(10)]
    df = _make_df(rows)

    result = audit_property(df, "Monte Castro", "departamento", 3, 72.0, ADYACENTES)

    assert result.n_comparables == 30  # los 10 de 150m2 quedan afuera del pool


def test_ambientes_tolerance_excludes_far_off_room_counts():
    rows = [_comp(f"MC{i}", "Monte Castro", 1800, ambientes=3) for i in range(30)]
    rows += [_comp(f"MC-mono-{i}", "Monte Castro", 2500, ambientes=1) for i in range(10)]
    df = _make_df(rows)

    result = audit_property(df, "Monte Castro", "departamento", 3, 72.0, ADYACENTES)

    assert result.n_comparables == 30  # los monoambientes (ambientes=1) quedan afuera


def test_tipo_and_condicion_filters_are_strict():
    rows = [_comp(f"MC{i}", "Monte Castro", 1800) for i in range(30)]
    rows += [_comp(f"MC-ph-{i}", "Monte Castro", 2000, tipo="ph") for i in range(10)]
    rows += [_comp(f"MC-pozo-{i}", "Monte Castro", 2200, condicion="pozo") for i in range(10)]
    df = _make_df(rows)

    result = audit_property(df, "Monte Castro", "departamento", 3, 72.0, ADYACENTES)

    assert result.n_comparables == 30  # ni los PH ni los "pozo" entran al pool de un departamento usado


def test_percentil_sujeto_reflects_position_among_comparables():
    rows = [_comp(f"MC{i}", "Monte Castro", 1000 + i * 100) for i in range(30)]  # 1000..3900
    df = _make_df(rows)

    barato = audit_property(df, "Monte Castro", "departamento", 3, 72.0, ADYACENTES, usd_m2_sujeto=500)
    caro = audit_property(df, "Monte Castro", "departamento", 3, 72.0, ADYACENTES, usd_m2_sujeto=5000)

    assert barato.percentil_sujeto == 0.0
    assert caro.percentil_sujeto == 100.0


def test_excluir_portal_id_removes_subject_from_its_own_pool():
    rows = [_comp(f"MC{i}", "Monte Castro", 1800) for i in range(30)]
    df = _make_df(rows)

    result = audit_property(
        df, "Monte Castro", "departamento", 3, 72.0, ADYACENTES, excluir_portal_id="MC0"
    )
    assert result.n_comparables == 29  # sin auto-comparación


def test_mi_propiedad_and_a_candidate_use_the_identical_code_path():
    """Regla anti-sesgo: no hay ninguna rama especial para 'mi propiedad' —
    la misma llamada con los mismos parámetros da el mismo resultado sin
    importar a qué sujeto representen."""
    rows = [_comp(f"MC{i}", "Monte Castro", 1800 + i) for i in range(30)]
    df = _make_df(rows)

    mi_propiedad = audit_property(df, "Monte Castro", "departamento", 3, 72.0, ADYACENTES, usd_m2_sujeto=1806.0)
    candidata_identica = audit_property(df, "Monte Castro", "departamento", 3, 72.0, ADYACENTES, usd_m2_sujeto=1806.0)

    assert mi_propiedad == candidata_identica
