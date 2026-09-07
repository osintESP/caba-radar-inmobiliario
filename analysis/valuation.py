"""Motor de valuación — Capa 1: comparables (PLAN-radar-inmobiliario.md,
sección 10).

Mismo tipo, barrio (o adyacente si el barrio solo no alcanza), m² ±15%,
ambientes ±1, condición "usado", activos (el snapshot ya solo trae avisos
activos hoy — el histórico de 90 días llega con F6/F7). Mediana y
percentiles 25/75 de USD/m². **Con menos de 30 comparables, no se emite
veredicto** — es un umbral real, no decorativo: con los datos de hoy,
Monte Castro solo (departamento/usado/m² parecido a 72) tiene 29
comparables, uno por debajo del corte.

**Regla anti-sesgo (sección 10):** `audit_property()` no sabe ni le
importa si el sujeto es "mi propiedad" o un aviso candidato cualquiera —
recibe barrio/tipo/ambientes/m² como cualquier otro llamador y corre
exactamente el mismo filtro y el mismo umbral. No existe (ni debe
agregarse) una rama de código distinta para la propiedad propia.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd

MIN_COMPARABLES = 30
M2_TOLERANCE = 0.15
AMBIENTES_TOLERANCE = 1


@dataclass
class ComparableAudit:
    n_comparables: int
    scope: str  # 'barrio' | 'barrio+adyacentes' | 'insuficiente'
    usd_m2_mediana: Optional[float]
    usd_m2_p25: Optional[float]
    usd_m2_p75: Optional[float]
    percentil_sujeto: Optional[float]  # 0-100: dónde cae el USD/m² del sujeto entre los comparables
    veredicto: str  # 'ok' | 'insuficiente'


def _filter_pool(
    df: pd.DataFrame,
    barrios: list[str],
    tipo: str,
    ambientes: Optional[int],
    m2_cubiertos: float,
    condicion: str,
) -> pd.DataFrame:
    mask = (
        df["barrio"].isin(barrios)
        & (df["tipo"] == tipo)
        & (df["condicion"] == condicion)
        & df["m2_cubiertos"].notna()
        & df["usd_m2"].notna()
        & df["m2_cubiertos"].between(m2_cubiertos * (1 - M2_TOLERANCE), m2_cubiertos * (1 + M2_TOLERANCE))
    )
    if ambientes is not None:
        mask &= df["ambientes"].between(ambientes - AMBIENTES_TOLERANCE, ambientes + AMBIENTES_TOLERANCE)
    return df[mask]


def audit_property(
    df: pd.DataFrame,
    barrio: str,
    tipo: str,
    ambientes: Optional[int],
    m2_cubiertos: float,
    adyacentes: dict[str, list[str]],
    usd_m2_sujeto: Optional[float] = None,
    condicion: str = "usado",
    min_comparables: int = MIN_COMPARABLES,
    excluir_portal_id: Optional[str] = None,
) -> ComparableAudit:
    """Audita un sujeto (propiedad propia o candidata, da igual) contra
    comparables reales. `excluir_portal_id` saca al propio aviso de su
    pool cuando el sujeto ya está en `df` (nunca se compara contra sí
    mismo)."""
    if excluir_portal_id is not None and "portal_id" in df.columns:
        df = df[df["portal_id"] != excluir_portal_id]

    pool = _filter_pool(df, [barrio], tipo, ambientes, m2_cubiertos, condicion)
    scope = "barrio"

    if len(pool) < min_comparables:
        barrios_ext = [barrio, *adyacentes.get(barrio, [])]
        pool_ext = _filter_pool(df, barrios_ext, tipo, ambientes, m2_cubiertos, condicion)
        if len(pool_ext) > len(pool):
            pool = pool_ext
            scope = "barrio+adyacentes"

    if len(pool) < min_comparables:
        return ComparableAudit(
            n_comparables=len(pool),
            scope="insuficiente",
            usd_m2_mediana=None,
            usd_m2_p25=None,
            usd_m2_p75=None,
            percentil_sujeto=None,
            veredicto="insuficiente",
        )

    p25, p50, p75 = (float(v) for v in pool["usd_m2"].quantile([0.25, 0.5, 0.75]))
    percentil_sujeto = None
    if usd_m2_sujeto is not None:
        percentil_sujeto = float((pool["usd_m2"] < usd_m2_sujeto).mean() * 100)

    return ComparableAudit(
        n_comparables=len(pool),
        scope=scope,
        usd_m2_mediana=p50,
        usd_m2_p25=p25,
        usd_m2_p75=p75,
        percentil_sujeto=percentil_sujeto,
        veredicto="ok",
    )
