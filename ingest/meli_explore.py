"""Spike manual, correr UNA VEZ (a mano) antes de confiar en run_daily.py.

Objetivo: confirmar contra la API real de Mercado Libre, con un access_token
válido, qué parámetros de búsqueda realmente filtran resultados —
categoría de inmuebles, operación "venta", y barrio — porque el acceso
anónimo cambió y las respuestas ya no traen `available_filters` para
descubrirlo de forma programática (ver PLAN-radar-inmobiliario.md, sección 7,
y el comentario al inicio de ingest/meli_client.py).

Qué hace:
1. Prueba una combinación de parámetros candidatos contra /sites/MLA/search.
2. Vuelca cada respuesta cruda a tests/fixtures/meli_search_<intento>.json.
3. Para el primer resultado de cada búsqueda que devuelva resultados, además
   vuelca el item completo (GET /items/{id}) a tests/fixtures/meli_item_<id>.json
   — esas fixtures son las que usan los tests de normalización.
4. Imprime un resumen para que la persona que corre esto decida a mano qué
   parámetros quedan en config/barrios.yaml (meli_neighborhood_id) y en
   ingest/meli_client.py (categoría de inmuebles a usar).

Uso:
    ML_ACCESS_TOKEN=<access_token de una corrida de meli_auth_bootstrap> \\
        uv run python -m ingest.meli_explore
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures"

# Candidatos a probar. MLA1459 es, hasta donde se pudo confirmar sin acceso
# directo a la doc oficial (403 al fetchear), la categoría raíz de Inmuebles
# en MLA; puede no ser exacta. Probar varias variantes es el propósito de
# este script, no una limitación.
CANDIDATE_SEARCHES = [
    {"category": "MLA1459", "operation": "sale"},
    {"category": "MLA1459", "operation": "sale", "q": "Velez Sarsfield"},
    {"category": "MLA1459", "operation": "sale", "q": "Floresta"},
    {"category": "MLA1459", "operation": "sale", "q": "Monte Castro"},
]


def main() -> int:
    token = os.environ.get("ML_ACCESS_TOKEN")
    if not token:
        print("Falta ML_ACCESS_TOKEN en el entorno (correr meli_auth_bootstrap primero).", file=sys.stderr)
        return 1

    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    client = httpx.Client(base_url="https://api.mercadolibre.com", timeout=20.0)
    headers = {"Authorization": f"Bearer {token}"}

    summary = []
    for i, params in enumerate(CANDIDATE_SEARCHES, start=1):
        resp = client.get("/sites/MLA/search", params=params, headers=headers)
        out_path = FIXTURES_DIR / f"meli_search_{i}.json"
        out_path.write_text(json.dumps({"params": params, "status": resp.status_code, "body": _safe_json(resp)}, ensure_ascii=False, indent=2))

        n_results = 0
        first_item_id = None
        if resp.status_code == 200:
            body = resp.json()
            n_results = body.get("paging", {}).get("total", len(body.get("results", [])))
            results = body.get("results", [])
            if results:
                first_item_id = results[0].get("id")

        summary.append({"params": params, "status": resp.status_code, "n_results": n_results, "fixture": str(out_path)})

        if first_item_id:
            item_resp = client.get(f"/items/{first_item_id}", headers=headers)
            if item_resp.status_code == 200:
                item_path = FIXTURES_DIR / f"meli_item_{first_item_id}.json"
                item_path.write_text(json.dumps(item_resp.json(), ensure_ascii=False, indent=2))
                summary[-1]["item_fixture"] = str(item_path)

    client.close()

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(
        "\nRevisá las fixtures en tests/fixtures/. Con los resultados reales, "
        "actualizá ATTRIBUTE_IDS en ingest/meli_client.py y los "
        "meli_neighborhood_id en config/barrios.yaml."
    )
    return 0


def _safe_json(resp: httpx.Response):
    try:
        return resp.json()
    except ValueError:
        return {"raw_text": resp.text}


if __name__ == "__main__":
    raise SystemExit(main())
