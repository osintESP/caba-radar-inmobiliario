"""Brecha neta — F5, PLAN-radar-inmobiliario.md sección 2.

La columna que debería ordenar toda la app: no el precio de lista, sino
cuánto hay que poner de más para pasar de "mi propiedad" a cada
candidata.

```
neto_venta   = precio_venta_mio − comisión_venta·(1+IVA) − impuesto_transferencia − gastos_fijos
costo_compra = precio_compra_negociado + sellos·sellos_a_mi_cargo_pct
             + escritura + comisión_compra·(1+IVA) + gastos_fijos
brecha_neta  = costo_compra − neto_venta
```

`precio_compra_negociado = precio_lista × (1 − pct_negociacion_estimado)`.
El pct ya no es un único valor global: se ajusta en dos franjas según el
`percentil_zona` de la candidata (F4, analysis/valuation.py) — por encima
de la mediana de sus comparables hay más margen para pedir descuento que
por debajo (PLAN sección 3.3, "ajuste por aviso"). Es un primer paso
heurístico hacia ese ajuste, no el blend estadístico completo (+ días en
mercado, recortes previos, override local), que es trabajo de F7 y
necesita ≥90 días de datos propios para no ser puro relleno.
"""

from __future__ import annotations

from typing import Any, Optional


def pct_negociacion_estimado(percentil_zona: Optional[float], costos: dict[str, Any]) -> float:
    """Descuento a pedir en la negociación. Sin comparables suficientes
    (`percentil_zona` None) usa el piso conservador `..._default`; si no,
    la franja alta o baja según esté por encima o por debajo de la
    mediana de sus comparables."""
    if percentil_zona is None:
        return costos["brecha_negociacion_pct_default"]
    if percentil_zona > 50:
        return costos["brecha_negociacion_pct_alto"]
    return costos["brecha_negociacion_pct_bajo"]


def neto_venta(precio_venta_usd: float, costos: dict[str, Any]) -> float:
    """Lo que queda en mano al vender la propiedad propia, neto de
    comisión (con IVA), impuesto a la transferencia y gastos fijos."""
    comision = precio_venta_usd * costos["comision_venta_pct"] * (1 + costos["iva_sobre_comision"])
    impuesto = precio_venta_usd * costos["impuesto_transferencia_pct"]
    return precio_venta_usd - comision - impuesto - costos["gastos_fijos_usd"]


def costo_compra(precio_lista_usd: float, costos: dict[str, Any], percentil_zona: Optional[float] = None) -> float:
    """Lo que sale comprar una candidata: precio negociado (lista menos
    la brecha de negociación estimada, `pct_negociacion_estimado()`) más
    sellos, escritura, comisión de compra (con IVA) y gastos fijos."""
    precio_negociado = precio_lista_usd * (1 - pct_negociacion_estimado(percentil_zona, costos))
    sellos = precio_negociado * costos["sellos_pct"] * costos["sellos_a_mi_cargo_pct"]
    escritura = precio_negociado * costos["escritura_pct"]
    comision = precio_negociado * costos["comision_compra_pct"] * (1 + costos["iva_sobre_comision"])
    return precio_negociado + sellos + escritura + comision + costos["gastos_fijos_usd"]


def brecha_neta(
    precio_lista_usd: float,
    precio_venta_usd: float,
    costos: dict[str, Any],
    percentil_zona: Optional[float] = None,
) -> float:
    """Cuánto hay que poner de más (positivo) o cuánto sobra (negativo)
    para pasar de la propiedad propia a la candidata de `precio_lista_usd`."""
    return costo_compra(precio_lista_usd, costos, percentil_zona) - neto_venta(precio_venta_usd, costos)
