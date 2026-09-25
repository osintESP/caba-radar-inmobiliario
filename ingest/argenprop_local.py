"""Scraping de Argenprop desde la Mac (IP residencial), no desde Actions.

Argenprop está detrás de un WAF que devuelve 0 avisos a las IPs de
datacenter de GitHub Actions (verificado 2026-09-07 y de nuevo 2026-09-25
con .github/workflows/test-f2-browsers.yml), mientras que desde una
conexión hogareña funciona perfecto. Por eso este módulo corre en la Mac
(programado con launchd, ver scripts/launchd/) y deja los registros crudos
del día en `data/argenprop/YYYY-MM-DD.parquet`; la corrida diaria de
Actions los suma al snapshot (`config/barrios.yaml: fuentes.argenprop:
local`, ver ingest/snapshot.py::load_argenprop_local).

Uso:
    uv run python -m ingest.argenprop_local            # solo escribe el archivo
    uv run python -m ingest.argenprop_local --push     # + commit y push a main
    uv run python -m ingest.argenprop_local --max-pages 1   # prueba corta
"""

from __future__ import annotations

import argparse
import datetime as dt
import subprocess
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from ingest import argenprop_scraper
from ingest.browser_utils import ChallengePageError, browser_session
from ingest.snapshot import ARGENPROP_LOCAL_DIR, CONFIG_DIR, all_barrios, load_yaml

REPO_DIR = Path(__file__).resolve().parent.parent


def _git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(REPO_DIR), *args], check=True, capture_output=True, text=True).stdout.strip()


def push_archivo(path: Path, fecha: str) -> None:
    """Commitea y pushea SOLO el archivo del día, sin tocar otros cambios que
    pueda haber en el working tree (autostash durante el rebase)."""
    rama = _git("rev-parse", "--abbrev-ref", "HEAD")
    if rama != "main":
        print(f"AVISO: el repo está en la rama '{rama}', no en main — no se pushea. El archivo quedó en {path}.")
        return
    _git("pull", "--rebase", "--autostash", "origin", "main")
    _git("add", str(path))
    if not _git("diff", "--cached", "--name-only", "--", str(path)):
        print("Sin cambios en el archivo de hoy, no se commitea.")
        return
    _git("commit", "-m", f"argenprop {fecha}", "--", str(path))
    _git("push", "origin", "main")
    print(f"Pusheado: argenprop {fecha}")


def scrape_combos(browser: Any, barrios_cfg: dict[str, Any], max_pages: Optional[int]) -> tuple[list[dict[str, Any]], int]:
    """Recorre barrio x tipología. Solo se guardan combinaciones COMPLETAS:
    una a medio paginar haría que price_events tome las páginas faltantes
    como avisos desaparecidos. Ante el captcha del WAF se frena todo (no
    tiene sentido seguir pidiendo a un sitio que está diciendo que paremos);
    lo ya completo se guarda igual. Devuelve (registros, combos pendientes)."""
    combos = [(n, s, t) for n, s in all_barrios(barrios_cfg) for t in barrios_cfg["tipologias"]]
    records: list[dict[str, Any]] = []
    for i, (nombre, slug, tipo) in enumerate(combos):
        try:
            combo = list(argenprop_scraper.search_barrio_tipo(browser, nombre, slug, tipo, max_pages=max_pages))
        except ChallengePageError:
            print(f"FRENO: Argenprop pidió captcha en {nombre}/{tipo}. Quedan {len(combos) - i} combinaciones sin scrapear hoy.")
            return records, len(combos) - i
        except Exception as exc:  # noqa: BLE001 — un combo con error de red no tira los demás
            print(f"AVISO: {nombre}/{tipo} falló, se lo salta: {exc}")
            continue
        print(f"  {nombre} / {tipo}: {len(combo)}", flush=True)
        records.extend(combo)
    return records, 0


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--push", action="store_true", help="commitear y pushear el archivo a origin/main")
    parser.add_argument("--max-pages", type=int, default=None, help="acotar páginas por barrio/tipo (prueba)")
    args = parser.parse_args(argv)

    captured_at = dt.datetime.now(dt.timezone.utc).isoformat()
    fecha = captured_at[:10]  # misma convención (UTC) que los snapshots de Actions
    barrios_cfg = load_yaml(CONFIG_DIR / "barrios.yaml")

    print(f"[{captured_at}] Argenprop local: arrancando.", flush=True)
    with browser_session() as browser:
        records, pendientes = scrape_combos(browser, barrios_cfg, args.max_pages)

    if not records:
        # Si el WAF empezara a bloquear también la IP de casa, no se pisa el
        # archivo de ayer con uno vacío: Actions sigue usando el último bueno
        # (dentro de argenprop_local_max_dias) y después lo omite.
        print("ERROR: Argenprop no devolvió avisos. No se escribe nada.")
        return 1

    con_precio = sum(r.get("price_amount") is not None for r in records)
    print(f"{len(records)} avisos ({con_precio} con precio). Combinaciones sin completar: {pendientes}.")

    df = pd.DataFrame(records).drop_duplicates(subset="portal_id")
    df["captured_at"] = captured_at
    ARGENPROP_LOCAL_DIR.mkdir(parents=True, exist_ok=True)
    path = ARGENPROP_LOCAL_DIR / f"{fecha}.parquet"
    df.to_parquet(path, index=False)
    print(f"Escrito {path}")

    if args.push:
        push_archivo(path, fecha)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
