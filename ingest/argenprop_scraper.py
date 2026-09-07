"""Scraper de Argenprop (F2). Requiere navegador real — ver
ingest/browser_utils.py, incluida la advertencia sobre IPs de datacenter.

Igual que Zonaprop, la página de LISTADO ya trae casi todo: precio,
dirección, m² cubiertos, dormitorios, antigüedad — vía una lista de
`<li>` con ícono + texto (`card__main-features`) más un `<a class="card"
...>` con varios atributos de datos (`idaviso`, `ambientes`,
`dormitorios`, `montooperacion`, `idmoneda`). Confirmado contra HTML real
(spike de esta sesión): 20/20 tarjetas parseadas en una página de Monte
Castro, incluyendo dirección exacta ("Miranda 5000").

Limitaciones conocidas, documentadas en vez de adivinadas:
- Solo se confirmaron los íconos `superficie_cubierta`, `cantidad_dormitorios`
  y `antiguedad` contra HTML real. `cantidad_ambientes`, `cantidad_banos` y
  el ícono de cochera son nombres razonables pero NO confirmados — si
  aparecen con otro nombre, el campo queda None (nunca imputado) hasta
  ajustar `FEATURE_ICON_MAP`.
- El atributo `ambientes=""` viene vacío en al menos un caso observado; se
  usa como fallback el número en la URL (".../N-ambiente(s)--...",
  "monoambiente" -> 1).
- `condicion` se infiere de `antiguedad`: "A Estrenar" -> pozo, un número
  de años -> usado. Si falta el dato de antigüedad, ambos quedan None.
"""

from __future__ import annotations

import re
from typing import Any, Optional
from urllib.parse import urljoin

from playwright.sync_api import Browser

from ingest.browser_utils import fetch_rendered_html

BASE_URL = "https://www.argenprop.com"

TIPO_PLURAL = {
    "departamento": "departamentos",
    "ph": "ph",
    "casa": "casas",
}

_CARD_TAG_RE = re.compile(r'<a href="(/[^"]+--\d+)"[^>]*class="card "[^>]*idaviso="\d+"[^>]*>')
_ATTR_RE = re.compile(r'([a-zA-Z_][a-zA-Z0-9_-]*)="([^"]*)"')
_PRICE_RE = re.compile(r'card__price">\s*(?:<span[^>]*>([^<]*)</span>)?\s*([^<]*)<')
_ADDRESS_RE = re.compile(r'card__address"[^>]*>\s*([^<]*)<')
_TITLE_RE = re.compile(r'card__title">([^<]*)<')
_IMAGE_RE = re.compile(r'src="(https://www\.argenprop\.com/static-content/[^"]+)"')
_FEATURES_BLOCK_RE = re.compile(r'card__main-features">(.*?)</ul>', re.S)
_FEATURE_ITEM_RE = re.compile(r'<i class="([^"]*)"></i>\s*<span>\s*([^<]*)</span>')
_TOTAL_RE = re.compile(r"<title>\s*(\d+)\s")
_AMBIENTES_URL_RE = re.compile(r"-(\d+)-ambientes?--")
_PISO_EN_DIRECCION_RE = re.compile(r"[Pp]iso\s+(\d+)")

_NUMERIC_RE = re.compile(r"[\d.,]+")


def _parse_number(text: str) -> Optional[float]:
    m = _NUMERIC_RE.search(text)
    if not m or not any(ch.isdigit() for ch in m.group()):
        return None
    return float(m.group().replace(".", "").replace(",", "."))


def build_search_url(tipo: str, barrio_slug: str, page: int = 1) -> str:
    base = f"{BASE_URL}/{TIPO_PLURAL[tipo]}/venta/{barrio_slug}"
    return base if page == 1 else f"{base}?pagina-{page}"


def total_results(html: str) -> Optional[int]:
    m = _TOTAL_RE.search(html)
    return int(m.group(1)) if m else None


def _ambientes_from_url(url: str) -> Optional[int]:
    if "monoambiente" in url:
        return 1
    m = _AMBIENTES_URL_RE.search(url)
    return int(m.group(1)) if m else None


# TODO(spike): confirmar cantidad_ambientes/cantidad_banos/cochera contra
# más fixtures reales — solo superficie_cubierta, cantidad_dormitorios y
# antiguedad están confirmados.
_FEATURE_FIELD_MAP = {
    "superficie_cubierta": "m2_cubiertos",
    "superficie_total": "m2_total",
    "cantidad_dormitorios": "dormitorios",
    "cantidad_ambientes": "ambientes",
    "cantidad_banos": "banos",
    "cochera": "cocheras",
    "cantidad_cocheras": "cocheras",
}


def _parse_features(html_block: str) -> dict[str, Any]:
    out: dict[str, Any] = {
        "m2_cubiertos": None,
        "m2_total": None,
        "dormitorios": None,
        "ambientes": None,
        "banos": None,
        "cocheras": None,
        "antiguedad": None,
        "condicion": None,
    }
    for icon_class, text in _FEATURE_ITEM_RE.findall(html_block):
        icon = icon_class.replace("basico1-icon-", "").strip()
        text = text.strip()
        if icon == "antiguedad":
            if "estrenar" in text.lower():
                out["antiguedad"] = 0
                out["condicion"] = "pozo"
            else:
                n = _parse_number(text)
                if n is not None:
                    out["antiguedad"] = int(n)
                    out["condicion"] = "usado"
            continue
        field = _FEATURE_FIELD_MAP.get(icon)
        if not field:
            continue
        n = _parse_number(text)
        out[field] = int(n) if field != "m2_cubiertos" and field != "m2_total" and n is not None else n
    return out


def parse_search_results(html: str, tipo: str, barrio_hint: str) -> list[dict[str, Any]]:
    tag_matches = list(_CARD_TAG_RE.finditer(html))
    results: list[dict[str, Any]] = []

    for i, m in enumerate(tag_matches):
        tag_attrs = dict(_ATTR_RE.findall(m.group(0)))
        idaviso = tag_attrs.get("idaviso")
        if not idaviso:
            continue

        start = m.end()
        end = tag_matches[i + 1].start() if i + 1 < len(tag_matches) else min(len(html), start + 6000)
        chunk = html[start:end]

        url = urljoin(BASE_URL, m.group(1))

        price_match = _PRICE_RE.search(chunk)
        currency_text = (price_match.group(1) or "") if price_match else ""
        amount_text = (price_match.group(2) or "") if price_match else ""
        price_amount = _parse_number(amount_text) if amount_text else None
        if "USD" in currency_text.upper():
            price_currency = "USD"
        elif price_amount is not None:
            price_currency = "ARS"
        else:
            price_currency = None

        address_match = _ADDRESS_RE.search(chunk)
        direccion = address_match.group(1).strip() if address_match else None
        piso_match = _PISO_EN_DIRECCION_RE.search(direccion) if direccion else None
        piso = int(piso_match.group(1)) if piso_match else None

        title_match = _TITLE_RE.search(chunk)
        image_match = _IMAGE_RE.search(chunk)
        features_block = _FEATURES_BLOCK_RE.search(chunk)
        features = _parse_features(features_block.group(1)) if features_block else _parse_features("")

        ambientes = features.get("ambientes")
        if ambientes is None:
            raw_ambientes = tag_attrs.get("ambientes")
            ambientes = int(raw_ambientes) if raw_ambientes and raw_ambientes.isdigit() else _ambientes_from_url(url)

        dormitorios = features.get("dormitorios")
        if dormitorios is None and tag_attrs.get("dormitorios", "").isdigit():
            dormitorios = int(tag_attrs["dormitorios"])

        results.append(
            {
                "portal": "argenprop",
                "portal_id": f"AP{idaviso}",
                "url": url,
                "status": "active",
                "price_amount": price_amount,
                "price_currency": price_currency,
                "expensas_ars": None,  # TODO: no confirmado en la tarjeta de listado
                "direccion": direccion,
                "titulo": title_match.group(1).strip() if title_match else None,
                "imagen_url": image_match.group(1) if image_match else None,
                "tipo": tipo,
                "barrio": barrio_hint,
                "ambientes": ambientes,
                "dormitorios": dormitorios,
                "banos": features.get("banos"),
                "cocheras": features.get("cocheras"),
                "m2_total": features.get("m2_total"),
                "m2_cubiertos": features.get("m2_cubiertos"),
                "antiguedad": features.get("antiguedad"),
                "condicion": features.get("condicion"),
                "piso": piso,
                "ascensor": None,
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
    # ~20 tarjetas por página, confirmado empíricamente.
    n_pages_estimate = max(1, (total + 19) // 20)
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
