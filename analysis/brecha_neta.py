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

`precio_compra_negociado = precio_lista × (1 − brecha_negociacion_pct)`.
Para esta primera versión `brecha_negociacion_pct` es un único valor
global configurable en `config/costos.yaml` — el blend estadístico por
fuente de la sección 3.3 (Índice M² Real + ajuste de zona + ajuste por
aviso + override local) es trabajo de F7, que necesita ≥90 días de
datos propios para no ser puro relleno.
"""

from __future__ import annotations

from typing import Any


def neto_venta(precio_venta_usd: float, costos: dict[str, Any]) -> float:
    """Lo que queda en mano al vender la propiedad propia, neto de
    comisión (con IVA), impuesto a la transferencia y gastos fijos."""
    comision = precio_venta_usd * costos["comision_venta_pct"] * (1 + costos["iva_sobre_comision"])
    impuesto = precio_venta_usd * costos["impuesto_transferencia_pct"]
    return precio_venta_usd - comision - impuesto - costos["gastos_fijos_usd"]


def costo_compra(precio_lista_usd: float, costos: dict[str, Any]) -> float:
    """Lo que sale comprar una candidata: precio negociado (lista menos
    la brecha de negociación estimada de la zona) más sellos, escritura,
    comisión de compra (con IVA) y gastos fijos."""
    precio_negociado = precio_lista_usd * (1 - costos["brecha_negociacion_pct"])
    sellos = precio_negociado * costos["sellos_pct"] * costos["sellos_a_mi_cargo_pct"]
    escritura = precio_negociado * costos["escritura_pct"]
    comision = precio_negociado * costos["comision_compra_pct"] * (1 + costos["iva_sobre_comision"])
    return precio_negociado + sellos + escritura + comision + costos["gastos_fijos_usd"]


def brecha_neta(precio_lista_usd: float, precio_venta_usd: float, costos: dict[str, Any]) -> float:
    """Cuánto hay que poner de más (positivo) o cuánto sobra (negativo)
    para pasar de la propiedad propia a la candidata de `precio_lista_usd`."""
    return costo_compra(precio_lista_usd, costos) - neto_venta(precio_venta_usd, costos)
