"""Orquesta una corrida de ingesta: barrios -> scraping de los 3 portales ->
normalización -> dedupe (F3) -> parquet del día. F4 (valuación) se corre
después, en ingest/run_daily.py, sobre el resultado de esta función.

Zonaprop/Argenprop son activables/desactivables por separado en
`config/barrios.yaml: fuentes`, porque a diferencia de Mercado Libre estos
dos portales necesitan un navegador real (ver ingest/browser_utils.py) y
su fiabilidad en un runner de GitHub Actions (IP de datacenter) es
variable — ver README.md.

El universo de barrios/ambientes es recortable desde `config/barrios.yaml:
alcance` (decisión del usuario, para iterar más fácil con menos datos por
corrida) — ver `all_barrios()` y el filtro de `ambientes_min` más abajo.

Dos diseños de costo bien distintos conviven acá:

- **Zonaprop/Argenprop**: la página de LISTADO ya trae casi todo (precio,
  m², ambientes, dirección) — no hace falta visitar el detalle de cada
  aviso. Se recorren todas las páginas de resultados todos los días, sin
  cupo ni caché de "conocidos". Corren PRIMERO, antes que ML: Cloudflare
  comparte reputación de IP entre los sitios que protege, y confirmado en
  la práctica que si ML ya hizo miles de requests desde la misma IP del
  runner, el challenge de Zonaprop empieza a fallar mucho más seguido
  (25 de 27 combinaciones en una corrida real) que corriendo Zonaprop
  "en frío". Un fallo acá se degrada sin abortar: se sigue solo con ML.
- **Mercado Libre**: la página de LISTADO es barata (1 request cada 48
  avisos) pero NO trae m²/ambientes — eso exige visitar el DETALLE de cada
  aviso (1 request por aviso). Con barrios de alto volumen, pedir el
  detalle de todos el mismo día no es sostenible, así que solo se pide
  para avisos NUEVOS, con un tope diario repartido parejo entre barrio x
  tipología (`scraping.max_new_detail_fetches_por_corrida`). Los avisos ya
  conocidos heredan sus atributos de detalle (no cambian) de la última vez
  que se los vio.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any, Optional

import pandas as pd
import yaml

from ingest import argenprop_scraper, dedupe, keywords, meli_scraper, zonaprop_scraper
from ingest.browser_utils import browser_session
from ingest.fx_mep import get_mep_rate
from ingest.normalize import normalize_batch

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
SNAPSHOTS_DIR = Path(__file__).resolve().parent.parent / "data" / "snapshots"

DETAIL_FIELDS = [
    "m2_total",
    "m2_cubiertos",
    "ambientes",
    "dormitorios",
    "banos",
    "cocheras",
    "antiguedad",
    "piso",
    "ascensor",
    "expensas_ars",
    "condicion",
]


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def all_barrios(barrios_cfg: dict[str, Any]) -> list[tuple[str, str]]:
    """Devuelve [(nombre, meli_slug), ...] para nucleo + propia (+ anillo,
    salvo que `alcance.anillo_activo` lo desactive — ver config/barrios.yaml,
    alcance reducido a pedido del usuario para iterar más fácil)."""
    incluir_anillo = barrios_cfg.get("alcance", {}).get("anillo_activo", True)
    roles = ("nucleo", "propia", "anillo") if incluir_anillo else ("nucleo", "propia")
    out: list[tuple[str, str]] = []
    for rol in roles:
        for entry in barrios_cfg.get(rol, []):
            out.append((entry["nombre"], entry["meli_slug"]))
    return out


def load_known_attributes(snapshots_dir: Path) -> dict[str, dict[str, Any]]:
    """Últimos atributos de DETALLE conocidos por portal_id, de todos los
    snapshots existentes. Un portal_id solo se considera "conocido" si en
    algún momento se le pudo pedir el detalle (si nunca se enriqueció por
    haber tocado el tope diario, sigue "no conocido" y se reintenta)."""
    known: dict[str, dict[str, Any]] = {}
    for path in sorted(snapshots_dir.glob("*.parquet")):
        try:
            df = pd.read_parquet(path)
        except Exception:
            continue
        if "portal_id" not in df.columns:
            continue
        for _, row in df.iterrows():
            if pd.isna(row.get("ambientes")) and pd.isna(row.get("m2_cubiertos")):
                continue  # nunca se enriqueció este aviso; se reintenta
            known[row["portal_id"]] = {field: row.get(field) for field in DETAIL_FIELDS}
    return known


def load_known_descriptions(snapshots_dir: Path) -> dict[str, dict[str, Any]]:
    """Descripción + tags ya extraídos por portal_id, de todos los
    snapshots existentes — no volver a visitar el detalle de un aviso
    solo para releer su descripción (no cambia)."""
    known: dict[str, dict[str, Any]] = {}
    for path in sorted(snapshots_dir.glob("*.parquet")):
        try:
            df = pd.read_parquet(path)
        except Exception:
            continue
        if "portal_id" not in df.columns or "descripcion" not in df.columns:
            continue
        for _, row in df.iterrows():
            if pd.isna(row.get("descripcion")):
                continue
            known[row["portal_id"]] = {"descripcion": row.get("descripcion"), "tags": row.get("tags")}
    return known


def apply_alcance_filter(rows: list[dict[str, Any]], ambientes_min: Optional[int]) -> list[dict[str, Any]]:
    """Alcance reducido (config/barrios.yaml: alcance.ambientes_min) — a
    diferencia de outliers (se flaggean, no se descartan, ver
    ingest/normalize.py), esto SÍ descarta filas: es una decisión explícita
    de encoger el universo para iterar más fácil, no una señal de calidad
    del dato. Un aviso sin ambientes informado no puede confirmarse >= al
    mínimo, así que también se descarta. `ambientes_min=None` es no-op."""
    if ambientes_min is None:
        return rows
    return [r for r in rows if r.get("ambientes") is not None and r["ambientes"] >= ambientes_min]


def load_known_portal_ids(snapshots_dir: Path) -> set[str]:
    """Todos los portal_id vistos alguna vez en un snapshot anterior — para
    marcar como "nuevo" cualquier aviso de hoy que no esté acá."""
    ids: set[str] = set()
    for path in snapshots_dir.glob("*.parquet"):
        try:
            ids.update(pd.read_parquet(path, columns=["portal_id"])["portal_id"].tolist())
        except Exception:
            continue
    return ids


def _scrape_browser_portal(
    scraper_module: Any,
    browser: Any,
    barrios_cfg: dict[str, Any],
    max_pages: Optional[int] = None,
) -> list[dict[str, Any]]:
    """Recorre barrio x tipología con un scraper basado en Playwright
    (Zonaprop o Argenprop, mismo contrato: search_barrio_tipo(browser,
    nombre, slug, tipo, max_pages=...)). `max_pages` sirve para acotar una
    corrida de prueba (ver README, verificación de viabilidad en GitHub
    Actions)."""
    records: list[dict[str, Any]] = []
    for barrio_nombre, barrio_slug in all_barrios(barrios_cfg):
        for tipo in barrios_cfg["tipologias"]:
            # Cada combo se aísla: si Cloudflare/WAF no soltó el contenido
            # real después de reintentar (ChallengePageError, ver
            # browser_utils.py) o pasa cualquier otro error de red, ese
            # combo puntual se salta con un aviso — no debe tirar los datos
            # ya juntados de los demás barrios/tipologías.
            try:
                records.extend(
                    scraper_module.search_barrio_tipo(browser, barrio_nombre, barrio_slug, tipo, max_pages=max_pages)
                )
            except Exception as exc:  # noqa: BLE001 — degradación por combo, no silenciosa
                print(f"AVISO: {scraper_module.__name__} falló para {barrio_nombre}/{tipo}, se lo salta: {exc}")
    return records


def _enrich_descriptions(
    records: list[dict[str, Any]],
    scraper_module: Any,
    browser: Any,
    snapshots_dir: Path,
    barrios_cfg: dict[str, Any],
) -> None:
    """Agrega `descripcion` + `tags` (ingest/keywords.py) a cada record, in
    place. Mismo patrón que el detalle de ML: caro (1 request por aviso),
    así que solo se pide para avisos nuevos, con tope diario, reusando lo
    ya extraído en corridas anteriores (la descripción no cambia)."""
    if not hasattr(scraper_module, "fetch_description"):
        return  # este portal todavía no soporta descripción (ver ingest/keywords.py)

    known = load_known_descriptions(snapshots_dir)
    max_new = barrios_cfg.get("scraping", {}).get("max_new_descriptions_por_corrida", 300)
    new_fetches = 0

    for record in records:
        pid = record["portal_id"]
        if pid in known:
            record["descripcion"] = known[pid]["descripcion"]
            record["tags"] = known[pid]["tags"]
            continue
        if new_fetches >= max_new:
            continue  # sin descripcion por hoy (None, nunca imputado); se reintenta mañana
        try:
            descripcion = scraper_module.fetch_description(browser, record["url"])
        except Exception as exc:  # noqa: BLE001 — un aviso puntual no debe tirar el resto
            print(f"AVISO: no se pudo traer la descripción de {pid}: {exc}")
            descripcion = None
        record["descripcion"] = descripcion
        record["tags"] = ",".join(keywords.extract_tags(descripcion)) if descripcion else None
        new_fetches += 1


def run_snapshot(
    captured_at: Optional[str] = None,
    barrios_cfg_path: Path = CONFIG_DIR / "barrios.yaml",
    costos_cfg_path: Path = CONFIG_DIR / "costos.yaml",
    snapshots_dir: Path = SNAPSHOTS_DIR,
) -> pd.DataFrame:
    captured_at = captured_at or dt.datetime.now(dt.timezone.utc).isoformat()
    fecha = captured_at[:10]

    barrios_cfg = load_yaml(barrios_cfg_path)
    costos_cfg = load_yaml(costos_cfg_path)

    mep = get_mep_rate(price_field=costos_cfg["fx"]["mep_price_field"])

    fuentes = barrios_cfg.get("fuentes", {})
    raw_records: list[dict[str, Any]] = []

    if fuentes.get("zonaprop", True) or fuentes.get("argenprop", True):
        # Zonaprop/Argenprop van ANTES que ML a propósito: Cloudflare
        # comparte reputación de IP entre los sitios que protege, y ML por
        # sí solo ya hace miles de requests desde la misma IP del runner.
        # Confirmado en la práctica: corriendo Zonaprop después de ~3hs de
        # ML, 25 de 27 combinaciones fallaron el challenge; en una prueba
        # corta y aislada (sin ML antes) pasaba sin problema. Un fallo acá
        # (Cloudflare/WAF, Chromium mal instalado, lo que sea) NO debe
        # impedir que ML corra igual — se degrada: se sigue solo con ML.
        try:
            with browser_session() as browser:
                if fuentes.get("zonaprop", True):
                    zonaprop_records = _scrape_browser_portal(zonaprop_scraper, browser, barrios_cfg)
                    _enrich_descriptions(zonaprop_records, zonaprop_scraper, browser, snapshots_dir, barrios_cfg)
                    raw_records.extend(zonaprop_records)
                if fuentes.get("argenprop", True):
                    raw_records.extend(_scrape_browser_portal(argenprop_scraper, browser, barrios_cfg))
        except Exception as exc:  # noqa: BLE001 — degradación intencional, no silenciosa: se imprime igual
            print(f"AVISO: Zonaprop/Argenprop fallaron, se sigue solo con ML. Error: {exc}")

    if fuentes.get("meli", True):
        known = load_known_attributes(snapshots_dir)
        max_new_fetches = barrios_cfg.get("scraping", {}).get("max_new_detail_fetches_por_corrida", 250)

        combos = [
            (barrio_nombre, barrio_slug, tipo)
            for barrio_nombre, barrio_slug in all_barrios(barrios_cfg)
            for tipo in barrios_cfg["tipologias"]
        ]
        # Cupo PAREJO por combinación barrio x tipología. Sin esto, un barrio
        # de alto volumen (ej. Flores) agota el cupo global entero y deja a
        # los demás —incluida "propia", donde está la propiedad a vender— en
        # cero el mismo día (pasó exactamente esto en la primera corrida
        # real). El resto que sobra después de darle su piso a cada combo se
        # reparte en orden de aparición (núcleo/propia primero, ver
        # all_barrios), no round-robin, porque ese orden ya refleja la
        # prioridad del plan.
        per_combo_cap = max(1, max_new_fetches // len(combos)) if combos else 0
        new_fetches = 0

        client = meli_scraper.make_client()
        pending_new: list[dict[str, Any]] = []  # avisos nuevos que no llegaron a enriquecerse en el primer paso
        try:
            for barrio_nombre, barrio_slug, tipo in combos:
                combo_new_fetches = 0
                for summary in meli_scraper.search_barrio_tipo(client, barrio_nombre, barrio_slug, tipo):
                    record = dict(summary)
                    portal_id = record["portal_id"]

                    if portal_id in known:
                        record.update(known[portal_id])
                    elif combo_new_fetches < per_combo_cap and new_fetches < max_new_fetches:
                        detail = meli_scraper.fetch_detail(client, record["url"])
                        record.update(detail)
                        combo_new_fetches += 1
                        new_fetches += 1
                    else:
                        pending_new.append(record)  # candidato para el cupo sobrante

                    raw_records.append(record)

            # Segundo paso: lo que sobró del cupo global (porque algún combo
            # tenía menos avisos nuevos que su piso) se reparte entre los
            # avisos que quedaron pendientes, en el mismo orden de prioridad.
            for record in pending_new:
                if new_fetches >= max_new_fetches:
                    break
                detail = meli_scraper.fetch_detail(client, record["url"])
                record.update(detail)
                new_fetches += 1
        finally:
            client.close()

    for record in raw_records:
        record["raw_json"] = json.dumps(
            {f: record.get(f) for f in ["portal_id", "url", "price_amount", "price_currency", *DETAIL_FIELDS]},
            ensure_ascii=False,
        )

    outliers_cfg = barrios_cfg.get("outliers", {})
    rows = normalize_batch(
        raw_records,
        mep=mep,
        usd_m2_min=outliers_cfg.get("usd_m2_min", 400),
        usd_m2_max=outliers_cfg.get("usd_m2_max", 8000),
        captured_at=captured_at,
    )

    ambientes_min = barrios_cfg.get("alcance", {}).get("ambientes_min")
    antes = len(rows)
    rows = apply_alcance_filter(rows, ambientes_min)
    if ambientes_min is not None:
        print(f"Alcance: descartados {antes - len(rows)} avisos con menos de {ambientes_min} ambientes o sin dato.")

    # F3: dedupe cross-portal/cross-inmobiliaria (ver ingest/dedupe.py). El
    # pHash de fotos es lo único que pega a la red acá, así que también
    # tiene un tope diario, reusando el hash ya calculado en corridas
    # anteriores para no volver a descargar la misma imagen.
    max_new_phash = barrios_cfg.get("scraping", {}).get("max_new_phash_fetches_por_corrida", 500)
    known_phashes = dedupe.load_known_phashes(snapshots_dir)
    dedupe_result = dedupe.find_duplicates(rows, known_phashes, max_new_phash_fetches=max_new_phash)
    known_portal_ids = load_known_portal_ids(snapshots_dir)
    for row in rows:
        pid = row["portal_id"]
        row["property_fingerprint"] = dedupe_result.fingerprint_by_portal_id.get(pid, pid)
        row["imagen_phash"] = dedupe_result.phash_by_portal_id.get(pid)
        row["es_nuevo"] = pid not in known_portal_ids

    df = pd.DataFrame(rows)

    snapshots_dir.mkdir(parents=True, exist_ok=True)
    out_path = snapshots_dir / f"{fecha}.parquet"
    df.to_parquet(out_path, index=False)  # sobreescribe si ya existía (idempotente por nombre)

    return df
