"""Scraper de Zonaprop (F2). Requiere navegador real — ver
ingest/browser_utils.py, incluida la advertencia sobre IPs de datacenter.

A diferencia de Mercado Libre, la página de LISTADO de Zonaprop ya trae
precio, expensas, m² (total), ambientes, baños y dirección — no hace falta
visitar el detalle de cada aviso para lo básico. Confirmado contra HTML
real (spike de esta sesión): 25/25 tarjetas parseadas correctamente en una
página de Monte Castro.

Limitaciones conocidas, documentadas en vez de adivinadas:
- La tarjeta de listado solo confirma "m² tot." (total), no "m² cub."
  (cubierta) de forma consistente. `m2_cubiertos` queda None cuando no se
  puede distinguir — nunca se asume igual a m2_total.
- No se pudo confirmar de dónde sale `condicion` (pozo/usado) en la
  tarjeta de listado; queda None hasta confirmarlo (posible candidato:
  visitar el detalle, igual que el enriquecimiento incremental de ML).
- `dormitorios`, `cocheras`, `antiguedad`, `piso`, `ascensor`, `expensas`
  no siempre aparecen en la tarjeta compacta; cuando no aparecen quedan
  None, nunca imputados.
"""

from __future__ import annotations

import re
from typing import Any, Optional
from urllib.parse import urljoin

from playwright.sync_api import Browser

from ingest.browser_utils import fetch_rendered_html

BASE_URL = "https://www.zonaprop.com.ar"

TIPO_PLURAL = {
    "departamento": "departamentos",
    "ph": "ph",
    "casa": "casas",
}

_CARD_SPLIT_RE = re.compile(r'<div class="postingCard-module__posting-container">')
_PRICE_RE = re.compile(r'POSTING_CARD_PRICE">([^<]*)<')
_EXPENSAS_RE = re.compile(r'data-qa="expensas">([^<]*)<')
_FEATURE_RE = re.compile(r'posting-main-features-span">([^<]*)<')
_ADDRESS_RE = re.compile(r'location-address[^"]*">([^<]*)<')
_LOCATION_RE = re.compile(r'POSTING_CARD_LOCATION">([^<]*)<')
_URL_RE = re.compile(r'<a href="([^"]+)"')
_PORTAL_ID_RE = re.compile(r"-(\d+)\.html")
_TOTAL_RE = re.compile(r'"offerCount":\s*"?(\d+)"?')
# Ojo: la primera <img> de la tarjeta suele ser el LOGO de la inmobiliaria
# ("empresas/..."), no una foto del aviso — las fotos reales están bajo
# "avisos/" y la primera trae "?isFirstImage=true".
_IMAGE_RE = re.compile(r'(https://imgar\.zonapropcdn\.com/avisos/[^"]+\?isFirstImage=true)')

_NUMERIC_RE = re.compile(r"[\d.,]+")


def _parse_number(text: str) -> Optional[float]:
    m = _NUMERIC_RE.search(text)
    if not m or not any(ch.isdigit() for ch in m.group()):
        return None
    return float(m.group().replace(".", "").replace(",", "."))


def build_search_url(tipo: str, barrio_slug: str, page: int = 1) -> str:
    tipo_plural = TIPO_PLURAL[tipo]
    if page == 1:
        return f"{BASE_URL}/{tipo_plural}-venta-{barrio_slug}.html"
    return f"{BASE_URL}/{tipo_plural}-venta-{barrio_slug}-pagina-{page}.html"


def total_results(html: str) -> Optional[int]:
    m = _TOTAL_RE.search(html)
    return int(m.group(1)) if m else None


def _parse_features(feature_texts: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {"m2_total": None, "m2_cubiertos": None, "ambientes": None, "banos": None, "cocheras": None}
    for text in feature_texts:
        low = text.lower()
        if "m²" in low and "tot" in low:
            out["m2_total"] = _parse_number(text)
        elif "m²" in low and "cub" in low:
            out["m2_cubiertos"] = _parse_number(text)
        elif "amb" in low:
            out["ambientes"] = int(_parse_number(text)) if _parse_number(text) is not None else None
        elif "baño" in low or "bano" in low:
            out["banos"] = int(_parse_number(text)) if _parse_number(text) is not None else None
        elif "coch" in low:
            out["cocheras"] = int(_parse_number(text)) if _parse_number(text) is not None else None
    return out


def parse_search_results(html: str, tipo: str, barrio_hint: str) -> list[dict[str, Any]]:
    chunks = _CARD_SPLIT_RE.split(html)[1:]  # [0] es todo lo previo a la primera tarjeta
    results: list[dict[str, Any]] = []

    for chunk in chunks:
        url_match = _URL_RE.search(chunk)
        if not url_match:
            continue
        url = urljoin(BASE_URL, url_match.group(1).split("?")[0])
        portal_id_match = _PORTAL_ID_RE.search(url)
        if not portal_id_match:
            continue

        price_match = _PRICE_RE.search(chunk)
        price_text = price_match.group(1).strip() if price_match else ""
        price_currency = "USD" if "USD" in price_text else ("ARS" if price_text else None)
        price_amount = _parse_number(price_text) if price_text else None

        expensas_match = _EXPENSAS_RE.search(chunk)
        expensas_ars = _parse_number(expensas_match.group(1)) if expensas_match else None

        address_match = _ADDRESS_RE.search(chunk)
        location_match = _LOCATION_RE.search(chunk)
        image_match = _IMAGE_RE.search(chunk)

        features = _parse_features(_FEATURE_RE.findall(chunk))

        results.append(
            {
                "portal": "zonaprop",
                "portal_id": f"ZP{portal_id_match.group(1)}",
                "url": url,
                "status": "active",
                "price_amount": price_amount,
                "price_currency": price_currency,
                "expensas_ars": expensas_ars,
                "direccion": address_match.group(1).strip() if address_match else None,
                "titulo": location_match.group(1).strip() if location_match else None,
                "imagen_url": image_match.group(1) if image_match else None,
                "tipo": tipo,
                "barrio": barrio_hint,
                "condicion": None,  # TODO: no confirmado en la tarjeta de listado
                "dormitorios": None,  # TODO: no confirmado en la tarjeta de listado
                "antiguedad": None,
                "piso": None,
                "ascensor": None,
                **features,
            }
        )
    return results


def search_barrio_tipo(browser: Browser, barrio_nombre: str, barrio_slug: str, tipo: str, max_pages: Optional[int] = None):
    url = build_search_url(tipo, barrio_slug, page=1)
    html = fetch_rendered_html(browser, url)

    seen_ids: set[str] = set()
    for r in parse_search_results(html, tipo, barrio_nombre):
        if r["portal_id"] not in seen_ids:
            seen_ids.add(r["portal_id"])
            yield r

    total = total_results(html) or 0
    # ~25 tarjetas por página, confirmado empíricamente — no es un total
    # documentado por Zonaprop, así que se recalcula cuántas páginas hacen
    # falta a partir del total real y se para si una página no trae nada.
    n_pages_estimate = max(1, (total + 24) // 25)
    if max_pages is not None:
        n_pages_estimate = min(n_pages_estimate, max_pages)

    page_num = 2
    while page_num <= n_pages_estimate:
        html = fetch_rendered_html(browser, build_search_url(tipo, barrio_slug, page=page_num))
        results = parse_search_results(html, tipo, barrio_nombre)
        if not results:
            break
        for r in results:
            if r["portal_id"] not in seen_ids:
                seen_ids.add(r["portal_id"])
                yield r
        page_num += 1
