"""Cliente autenticado de la API de Mercado Libre.

**DORMIDO / SIN USO** (septiembre 2026): confirmado en vivo que
`/sites/{site}/search` e `/items/{id}` devuelven 403 para apps no
certificadas, con o sin token — no es un problema de permisos de la app.
La ingesta real usa `ingest/meli_scraper.py` (web pública). Este módulo
queda documentado por si en el futuro se consigue certificación de partner
con Mercado Libre (contacto: vis-support@mercadolibre.com) y vuelve a ser
viable. Ver README.md y el addendum al final de PLAN-radar-inmobiliario.md.

IMPORTANTE — leer antes de tocar este archivo: la sección `ATTRIBUTE_IDS` y el
parseo de ubicación/condición de `extract_listing` son PROVISORIOS. El propio
PLAN-radar-inmobiliario.md advierte que la API cambió (acceso anónimo
restringido, `available_filters` ya no viene en las búsquedas), y no hay forma
honesta de confirmar de memoria los IDs de atributo/categoría/barrio
exactos. Además, Mercado Libre separa Inmuebles bajo una unidad de negocio
propia llamada **VIS** ("Vehículos, Inmuebles y Servicios"), con soporte
técnico y documentación distintos del resto del marketplace — no está
confirmado si `/sites/MLA/search` alcanza para leer avisos de venta o si
hace falta un endpoint bajo `/vis/...`. El spike de `ingest/meli_explore.py`
corre esto contra la API real con un token de una app registrada con
"Negocios: VIS", vuelca las respuestas a `tests/fixtures/`, y este módulo
se ajusta con esos datos reales antes de confiar en `run_daily.py`.

No cambia el contrato hacia afuera: `search_all_items` siempre devuelve una
lista de dicts en el formato `ExtractedListing` que espera `normalize.py`,
con `raw_json` siempre presente para poder re-parsear el histórico si esta
capa tenía un bug.
"""

from __future__ import annotations

import json
from typing import Any, Iterator, Optional

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

API_BASE = "https://api.mercadolibre.com"
SEARCH_MAX_RESULTS = 1000  # límite documentado de la API de búsqueda de ML
SEARCH_PAGE_SIZE = 50

# TODO(spike): confirmar/ajustar estos IDs contra las fixtures de meli_explore.py.
ATTRIBUTE_IDS = {
    "PROPERTY_TYPE": "tipo",
    "TOTAL_AREA": "m2_total",
    "COVERED_AREA": "m2_cubiertos",
    "ROOMS": "ambientes",
    "BEDROOMS": "dormitorios",
    "FULL_BATHROOMS": "banos",
    "PARKING_LOTS": "cocheras",
    "PROPERTY_AGE": "antiguedad",
    "FLOOR": "piso",
    "HAS_ELEVATOR": "ascensor",
    "EXPENSES": "expensas_ars",
    "PROPERTY_CONDITION": "condicion_raw",
}

# TODO(spike): confirmar valores reales que devuelve PROPERTY_CONDITION.
CONDICION_MAP = {
    "A estrenar": "pozo",
    "En construcción": "pozo",
    "En pozo": "pozo",
    "Usado": "usado",
}

_RETRYABLE = (httpx.TransportError, httpx.HTTPStatusError)


def _is_retryable_status(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in (429, 500, 502, 503, 504)
    return isinstance(exc, httpx.TransportError)


class MeliClient:
    def __init__(self, access_token: str, client: Optional[httpx.Client] = None) -> None:
        self._access_token = access_token
        self._client = client or httpx.Client(base_url=API_BASE, timeout=20.0)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._access_token}"}

    @retry(
        retry=retry_if_exception_type(_RETRYABLE),
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=1, min=2, max=20),
    )
    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        resp = self._client.get(path, params=params, headers=self._headers())
        if resp.status_code in (429, 500, 502, 503, 504):
            resp.raise_for_status()  # dispara el retry
        resp.raise_for_status()
        return resp.json()

    def search_page(self, params: dict[str, Any], offset: int, limit: int = SEARCH_PAGE_SIZE) -> dict[str, Any]:
        page_params = {**params, "offset": offset, "limit": limit}
        return self._get("/sites/MLA/search", page_params)

    def search_all(self, params: dict[str, Any]) -> Iterator[dict[str, Any]]:
        """Itera todos los resultados de una búsqueda, respetando el tope de
        1000 resultados por búsqueda documentado por ML."""
        offset = 0
        while offset < SEARCH_MAX_RESULTS:
            page = self.search_page(params, offset)
            results = page.get("results", [])
            if not results:
                return
            yield from results
            offset += len(results)
            if len(results) < SEARCH_PAGE_SIZE:
                return

    def get_item(self, item_id: str) -> dict[str, Any]:
        return self._get(f"/items/{item_id}", {})

    def close(self) -> None:
        self._client.close()


def _attr_dict(item: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for attr in item.get("attributes") or []:
        attr_id = attr.get("id")
        mapped = ATTRIBUTE_IDS.get(attr_id)
        if not mapped:
            continue
        value = attr.get("value_name")
        if value is None and attr.get("values"):
            value = attr["values"][0].get("name")
        out[mapped] = value
    return out


def _as_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        # Los value_name de ML suelen venir como "72 m²" o "72"; nos quedamos
        # con la parte numérica inicial.
        digits = "".join(ch for ch in str(value) if ch.isdigit() or ch in ".,").replace(",", ".")
        return float(digits) if digits else None
    except ValueError:
        return None


def _as_int(value: Any) -> Optional[int]:
    f = _as_float(value)
    return int(f) if f is not None else None


def extract_listing(item: dict[str, Any], barrio_hint: Optional[str] = None) -> dict[str, Any]:
    """Convierte un item crudo de la API de ML al formato ExtractedListing que
    espera ingest/normalize.py. Nunca imputa: lo que no está, queda None."""
    attrs = _attr_dict(item)

    location = item.get("location") or {}
    neighborhood = (location.get("neighborhood") or {}).get("name") or barrio_hint

    condicion_raw = attrs.get("condicion_raw")
    condicion = CONDICION_MAP.get(condicion_raw) if condicion_raw else None

    ascensor_raw = attrs.get("ascensor")
    ascensor = None
    if ascensor_raw is not None:
        ascensor = str(ascensor_raw).strip().lower() in ("sí", "si", "yes", "true")

    price = item.get("price")
    currency = item.get("currency_id")

    return {
        "portal": "meli",
        "portal_id": item.get("id"),
        "url": item.get("permalink"),
        "price_amount": float(price) if price is not None else None,
        "price_currency": currency,
        "expensas_ars": _as_float(attrs.get("expensas_ars")),
        "m2_total": _as_float(attrs.get("m2_total")),
        "m2_cubiertos": _as_float(attrs.get("m2_cubiertos")),
        "ambientes": _as_int(attrs.get("ambientes")),
        "dormitorios": _as_int(attrs.get("dormitorios")),
        "banos": _as_int(attrs.get("banos")),
        "cocheras": _as_int(attrs.get("cocheras")),
        "antiguedad": _as_int(attrs.get("antiguedad")),
        "piso": _as_int(attrs.get("piso")),
        "ascensor": ascensor,
        "tipo": (attrs.get("tipo") or "").strip().lower() or None,
        "condicion": condicion,
        "barrio": neighborhood,
        "lat": location.get("latitude"),
        "lon": location.get("longitude"),
        "titulo": item.get("title"),
        "descripcion": None,  # requiere GET /items/{id}/description aparte; no en F0/F1
        "raw_json": json.dumps(item, ensure_ascii=False),
        "status": item.get("status"),  # 'active'|'paused'|'closed' — señal de venta clave
    }
