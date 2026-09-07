"""Prueba acotada: ¿Zonaprop/Argenprop responden con contenido real desde
ESTE entorno? Se usa para validar viabilidad en GitHub Actions (IP de
datacenter) antes de habilitar `fuentes.zonaprop`/`fuentes.argenprop` en
`config/barrios.yaml` para la corrida diaria completa.

Sale con código != 0 si cualquiera de los dos portales no devuelve avisos,
para que el workflow se vea claramente rojo/verde en Actions.
"""

from __future__ import annotations

import sys

from ingest import argenprop_scraper as ap
from ingest import zonaprop_scraper as zp
from ingest.browser_utils import browser_session


def main() -> int:
    ok = True
    with browser_session() as browser:
        zp_results = list(zp.search_barrio_tipo(browser, "Monte Castro", "monte-castro", "departamento", max_pages=3))
        print(f"Zonaprop: {len(zp_results)} avisos ({len(set(r['portal_id'] for r in zp_results))} únicos)")
        if not zp_results:
            print("FALLO: Zonaprop no devolvió avisos.", file=sys.stderr)
            ok = False

        ap_results = list(ap.search_barrio_tipo(browser, "Monte Castro", "monte-castro", "departamento", max_pages=3))
        print(f"Argenprop: {len(ap_results)} avisos ({len(set(r['portal_id'] for r in ap_results))} únicos)")
        if not ap_results:
            print("FALLO: Argenprop no devolvió avisos.", file=sys.stderr)
            ok = False

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
