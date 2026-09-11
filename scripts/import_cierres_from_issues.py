"""Vuelca a data/manual/cierres_terceros.csv los issues abiertos con label
"cierre" (creados desde site/carga-cierre.html — F6, PLAN-radar-inmobiliario.md
sección 3.2 fuente A5). Corrida manual por ahora, no una GitHub Action:
correr después de que el corredor cargue un cierre.

Requiere `gh` autenticado contra el repo (misma herramienta que ya usa
.github/workflows/test-f2-browsers.yml para disparos manuales). Cada
issue procesado se cierra con un comentario, así --state open funciona
como deduplicación entre corridas sin necesitar una columna extra en el
CSV (que ya tiene un formato fijo, ver data/manual/cierres_terceros.csv).
"""

from __future__ import annotations

import csv
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = "osintESP/caba-radar-inmobiliario"
CSV_PATH = Path(__file__).resolve().parent.parent / "data" / "manual" / "cierres_terceros.csv"
CSV_FIELDS = ["fecha", "barrio", "tipo", "ambientes", "m2", "precio_publicado_usd", "precio_cierre_usd", "fuente", "confianza"]

# El cuerpo del issue lo arma site/carga-cierre.js como lista markdown:
# "- **campo**: valor". direccion_aprox se carga en el issue para
# contexto humano pero no tiene columna en el CSV (ver docstring).
_CAMPO_RE = re.compile(r"^-\s*\*\*(\w+)\*\*:\s*(.*)$", re.MULTILINE)


def _parse_body(body: str) -> dict[str, str]:
    return {campo: valor.strip() for campo, valor in _CAMPO_RE.findall(body)}


def _fetch_issues() -> list[dict]:
    result = subprocess.run(
        ["gh", "issue", "list", "--repo", REPO, "--label", "cierre", "--state", "open", "--json", "number,body"],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


def _append_rows(rows: list[dict[str, str]]) -> None:
    existe = CSV_PATH.exists()
    with CSV_PATH.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if not existe:
            writer.writeheader()
        for row in rows:
            writer.writerow({campo: row.get(campo, "s/d") for campo in CSV_FIELDS})


def _close_issue(number: int) -> None:
    subprocess.run(
        ["gh", "issue", "close", str(number), "--repo", REPO, "--comment", "Importado a data/manual/cierres_terceros.csv."],
        check=True,
    )


def main() -> int:
    issues = _fetch_issues()
    if not issues:
        print("Sin issues abiertos con label 'cierre'.")
        return 0

    rows = [_parse_body(issue["body"]) for issue in issues]
    _append_rows(rows)
    for issue in issues:
        _close_issue(issue["number"])

    print(f"OK: {len(issues)} cierre(s) importado(s) a {CSV_PATH}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
