"""Scraper de la web pública de Mercado Libre Inmuebles.

Reemplaza a `meli_client.py` (API oficial) como fuente de descubrimiento.
Verificado en vivo (septiembre 2026): `/sites/{site}/search` e `/items/{id}`
devuelven 403 para apps no certificadas, **con o sin token** — no es un
problema de permisos de la app, es una restricción de plataforma (ver
README.md y el addendum al final de PLAN-radar-inmobiliario.md). La web
pública sí responde 200 con un User-Agent normal.

Dos niveles de datos, de costo MUY distinto:

1. **Página de listado** (`_Desde_N_NoIndex_True`, 48 avisos por página):
   trae precio, dirección (solo a nivel "Capital Federal", no barrio),
   vendedor, URL y fecha de publicación vía un bloque `schema.org` (`ld+json`
   con `@graph` de `RealEstateListing`). Barata: 1 request cada 48 avisos,
   sin importar el volumen del barrio.

2. **Página de detalle** de cada aviso: da m²/ambientes/baños/condición —
   la variable de valuación. Cara: 1 request POR AVISO. Con barrios de
   volumen alto (Flores: ~1.900 deptos en venta) visitarlos TODOS todos los
   días no es sostenible ni cortés con el servicio.

Por eso `ingest/snapshot.py` solo pide detalle de avisos NUEVOS (no vistos
en snapshots anteriores), con un tope diario configurable
(`config/barrios.yaml: scraping.max_new_detail_fetches_por_corrida`). Los
avisos ya conocidos heredan sus atributos de detalle de la última vez que
se los vio (no cambian: m², ambientes, etc.) y solo refrescan precio/estado
desde la página de listado, mucho más barata.
"""

from __future__ import annotations

import datetime as dt
import json
import random
import re
import time
import unicodedata
from dataclasses import dataclass
from typing import Any, Iterator, Optional

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36 "
    "(+contacto personal, uso de baja frecuencia, radar-inmobiliario)"
)

BASE_URL = "https://inmuebles.mercadolibre.com.ar"
PAGE_SIZE = 48

TIPO_PLURAL = {
    "departamento": "departamentos",
    "ph": "ph",
    "casa": "casas",
}

# Rate limit cortés (PLAN-radar-inmobiliario.md sección 7): 2-4s con jitter,
# sin paralelismo. Un solo hilo, un solo httpx.Client compartido.
_MIN_DELAY = 2.0
_MAX_DELAY = 4.0

_LD_JSON_RE = re.compile(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', re.S)
_TOTAL_RE = re.compile(r'"total":(\d+)')
_PORTAL_ID_RE = re.compile(r"MLA-?(\d+)")

# Tabla "Características principales" (componente Andes) de la página de
# detalle: filas label -> value, la fuente confiable de m²/ambientes/etc.
# Confirmada contra un aviso real (usado, único, sin variaciones) en el
# spike — no confundir con el widget de "variaciones" de precio que traen
# los emprendimientos con múltiples unidades, que no es representativo del
# caso típico y no se parsea acá.
_SPEC_ROW_RE = re.compile(
    r'andes-table__header__container">([^<]+)</div></th>'
    r"<td[^>]*>(?:<span[^>]*>)?"
    r'<span[^>]*class="andes-table__column--value"[^>]*>([^<]*)</span>'
)
_ITEM_CONDITION_RE = re.compile(r'"itemCondition":"https?:(?:\\u002F|/){2}schema\.org(?:\\u002F|/)(\w+)"')

_NUMERIC_RE = re.compile(r"[\d.,]+")


def _parse_number(text: str) -> Optional[float]:
    m = _NUMERIC_RE.search(text)
    if not m:
        return None
    return float(m.group().replace(".", "").replace(",", "."))


def _parse_bool_si_no(text: str) -> Optional[bool]:
    t = text.strip().lower()
    if t == "sí":
        return True
    if t == "no":
        return False
    return None


# Ninguna antigüedad real en años pasa de ~150 — si el valor supera esto,
# la celda de MELI trajo el año de construcción en vez de la antigüedad
# (visto en vivo: "Antigüedad" = "1970"). Se convierte a antigüedad real
# en vez de guardar el año como si fuera años transcurridos.
_ANTIGUEDAD_MAX_PLAUSIBLE = 150


def _parse_antiguedad(text: str) -> Optional[int]:
    valor = _parse_number(text)
    if valor is None:
        return None
    valor = int(valor)
    if valor > _ANTIGUEDAD_MAX_PLAUSIBLE:
        return max(dt.date.today().year - valor, 0)
    return valor


# Ninguna unidad individual (depto/PH/casa) tiene más de esto en cocheras
# propias. Un valor más alto es casi siempre el atributo agregado de un
# "Emprendimiento" (la tabla describe el proyecto completo, no la unidad —
# ver docstring de fetch_detail) — se descarta a None en vez de propagar
# un número que sabemos que está mal, mismo criterio que m2_cubiertos
# (PLAN-radar-inmobiliario.md sección 8: nunca imputar/propagar dato falso).
_COCHERAS_MAX_PLAUSIBLE = 4


def _parse_cocheras(text: str) -> Optional[int]:
    valor = _parse_number(text)
    if valor is None:
        return None
    valor = int(valor)
    return valor if valor <= _COCHERAS_MAX_PLAUSIBLE else None


# label de la tabla -> (campo normalizado, parser)
_SPEC_FIELD_MAP = {
    "Superficie total": ("m2_total", _parse_number),
    "Superficie cubierta": ("m2_cubiertos", _parse_number),
    "Ambientes": ("ambientes", lambda t: int(_parse_number(t)) if _parse_number(t) is not None else None),
    "Dormitorios": ("dormitorios", lambda t: int(_parse_number(t)) if _parse_number(t) is not None else None),
    "Baños": ("banos", lambda t: int(_parse_number(t)) if _parse_number(t) is not None else None),
    "Cocheras": ("cocheras", _parse_cocheras),
    "Número de piso de la unidad": ("piso", lambda t: int(_parse_number(t)) if _parse_number(t) is not None else None),
    "Antigüedad": ("antiguedad", _parse_antiguedad),
    "Expensas": ("expensas_ars", _parse_number),
    "Ascensor": ("ascensor", _parse_bool_si_no),
}


def slugify(nombre: str) -> str:
    s = unicodedata.normalize("NFKD", nombre).encode("ascii", "ignore").decode()
    s = s.lower().strip()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def _sleep_jitter() -> None:
    time.sleep(random.uniform(_MIN_DELAY, _MAX_DELAY))


@retry(
    retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=1, min=2, max=20),
)
def _get(client: httpx.Client, url: str) -> httpx.Response:
    _sleep_jitter()
    resp = client.get(url, headers={"User-Agent": USER_AGENT}, follow_redirects=True, timeout=20.0)
    if resp.status_code in (429, 500, 502, 503, 504):
        resp.raise_for_status()  # dispara el retry
    resp.raise_for_status()
    return resp


def make_client() -> httpx.Client:
    return httpx.Client()


def _extract_ld_json_blocks(html: str) -> list[Any]:
    blocks = []
    for raw in _LD_JSON_RE.findall(html):
        try:
            blocks.append(json.loads(raw))
        except json.JSONDecodeError:
            continue
    return blocks


def parse_search_results(html: str, tipo: str, barrio_hint: str) -> list[dict[str, Any]]:
    """Extrae los avisos de una página de listado a partir del bloque
    schema.org `@graph`. Solo trae precio/dirección/vendedor/URL/fecha —
    ver docstring del módulo."""
    results: list[dict[str, Any]] = []
    for block in _extract_ld_json_blocks(html):
        graph = block.get("@graph") if isinstance(block, dict) else None
        if not graph:
            continue
        for entry in graph:
            if entry.get("@type") != "RealEstateListing":
                continue
            offers = entry.get("offers") or {}
            url = offers.get("url") or entry.get("mainEntityOfPage")
            m = _PORTAL_ID_RE.search(url or "")
            if not m:
                continue
            results.append(
                {
                    "portal": "meli",
                    "portal_id": f"MLA{m.group(1)}",
                    "url": url,
                    "status": "active",
                    "price_amount": offers.get("price"),
                    "price_currency": offers.get("priceCurrency"),
                    "titulo": entry.get("name"),
                    "seller": (entry.get("seller") or {}).get("name"),
                    "date_posted": entry.get("datePosted"),
                    "imagen_url": entry.get("image"),
                    "tipo": tipo,
                    "barrio": barrio_hint,
                }
            )
    return results


def total_results(html: str) -> Optional[int]:
    m = _TOTAL_RE.search(html)
    return int(m.group(1)) if m else None


def search_barrio_tipo(
    client: httpx.Client,
    barrio_nombre: str,
    barrio_slug: str,
    tipo: str,
    max_pages: Optional[int] = None,
) -> Iterator[dict[str, Any]]:
    """Itera los avisos de un barrio x tipología, paginando de a 48."""
    tipo_plural = TIPO_PLURAL[tipo]
    base = f"{BASE_URL}/{tipo_plural}/venta/capital-federal/{barrio_slug}/"

    resp = _get(client, base)
    html = resp.text
    seen_ids: set[str] = set()
    for r in parse_search_results(html, tipo, barrio_nombre):
        if r["portal_id"] not in seen_ids:
            seen_ids.add(r["portal_id"])
            yield r

    total = total_results(html) or 0
    n_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
    if max_pages is not None:
        n_pages = min(n_pages, max_pages)

    for page in range(1, n_pages):
        desde = page * PAGE_SIZE + 1
        url = f"{base}_Desde_{desde}_NoIndex_True"
        resp = _get(client, url)
        for r in parse_search_results(resp.text, tipo, barrio_nombre):
            if r["portal_id"] not in seen_ids:
                seen_ids.add(r["portal_id"])
                yield r


def fetch_detail(client: httpx.Client, url: str) -> dict[str, Any]:
    """Visita la página de un aviso puntual y extrae m²/ambientes/baños/
    condición/expensas/etc. de la tabla "Características principales".
    Campos ausentes de la tabla, o con un label que no reconocemos, quedan
    None — nunca se imputan (PLAN-radar-inmobiliario.md sección 8).

    Nota: en "Emprendimientos" (proyectos con varias unidades a distintos
    precios/m²) esta tabla describe el rango del proyecto completo, no una
    unidad puntual — es una limitación conocida, no un bug del parser.
    """
    resp = _get(client, url)
    html = resp.text

    fields: dict[str, Any] = {
        "m2_total": None,
        "m2_cubiertos": None,
        "ambientes": None,
        "dormitorios": None,
        "banos": None,
        "cocheras": None,
        "piso": None,
        "antiguedad": None,
        "expensas_ars": None,
        "ascensor": None,
    }
    for label, raw_value in _SPEC_ROW_RE.findall(html):
        mapped = _SPEC_FIELD_MAP.get(label.strip())
        if not mapped:
            continue
        field, parser = mapped
        fields[field] = parser(raw_value)

    condicion_match = _ITEM_CONDITION_RE.search(html)
    condicion = None
    if condicion_match:
        condicion = "pozo" if condicion_match.group(1) == "NewCondition" else "usado"

    return {**fields, "condicion": condicion, "descripcion": None}
