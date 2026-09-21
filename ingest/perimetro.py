"""Perímetro de búsqueda por barrio (config/barrios.yaml: perimetros).

Un barrio puede acotarse a un polígono de coordenadas (lista de [lat, lon])
para dejar afuera zonas que no interesan (ej. la traza del ferrocarril o una
avenida comercial). Sin polígono configurado, el barrio no se filtra.

Un aviso sin coordenadas conocidas NO se marca fuera de perímetro: no hay dato
para decidirlo (nunca se imputa) — queda visible hasta que se lo enriquezca.
"""

from __future__ import annotations

from typing import Any, Optional


def point_in_polygon(lat: float, lon: float, polygon: list[list[float]]) -> bool:
    """Ray casting. `polygon` es [[lat, lon], ...], sin repetir el primer punto."""
    inside = False
    n = len(polygon)
    j = n - 1
    for i in range(n):
        lat_i, lon_i = polygon[i]
        lat_j, lon_j = polygon[j]
        if (lon_i > lon) != (lon_j > lon):
            lat_cruce = (lat_j - lat_i) * (lon - lon_i) / (lon_j - lon_i) + lat_i
            if lat < lat_cruce:
                inside = not inside
        j = i
    return inside


def fuera_de_perimetro(
    barrio: Optional[str], lat: Optional[float], lon: Optional[float], perimetros: dict[str, list[list[float]]]
) -> bool:
    polygon = perimetros.get(barrio) if barrio else None
    if not polygon or len(polygon) < 3 or lat is None or lon is None:
        return False
    return not point_in_polygon(lat, lon, polygon)


def apply_perimetros(rows: list[dict[str, Any]], perimetros: dict[str, list[list[float]]]) -> None:
    """Agrega `fuera_de_perimetro` (bool) a cada fila, in place."""
    for row in rows:
        lat, lon = row.get("lat"), row.get("lon")
        lat = None if lat is None or lat != lat else float(lat)
        lon = None if lon is None or lon != lon else float(lon)
        row["fuera_de_perimetro"] = fuera_de_perimetro(row.get("barrio"), lat, lon, perimetros)
