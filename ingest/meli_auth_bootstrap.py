"""Script de un solo uso: autoriza la app de Mercado Libre por navegador y
carga ML_REFRESH_TOKEN en GitHub Secrets.

Mercado Libre exige que el `redirect_uri` registrado en la app sea HTTPS —
`http://localhost` no se acepta (confirmado al registrar la app: el propio
formulario de ML Developers dice "La dirección debe contener https://").
Por eso no hay servidor local levantando el callback: se usa
`site/oauth-callback.html`, publicado por GitHub Pages, que muestra el
`code` en pantalla para copiarlo a mano a esta terminal.

Uso (ver README.md para el checklist completo):

    ML_CLIENT_ID=... ML_CLIENT_SECRET=... \\
        uv run python -m ingest.meli_auth_bootstrap \\
        --redirect-uri https://<usuario>.github.io/<repo>/oauth-callback.html

Requisitos antes de correr esto:
  - GitHub Pages ya activado (Settings → Pages → Source → GitHub Actions)
    y con al menos un deploy hecho, para que oauth-callback.html resuelva.
  - El mismo `redirect_uri` registrado tal cual en la app de ML Developers.
  - ML_CLIENT_ID / ML_CLIENT_SECRET en el entorno local (no hace falta que
    estén todavía en GitHub Secrets — de hecho el resultado de este script
    es justamente lo que falta cargar ahí: ML_REFRESH_TOKEN).
"""

from __future__ import annotations

import argparse
import os
import sys
import webbrowser

from ingest.gh_secrets import set_secret
from ingest.meli_auth import build_auth_url, exchange_code


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", default=None, help="owner/repo; por defecto el del directorio actual")
    parser.add_argument("--redirect-uri", required=True, help="debe ser HTTPS y coincidir con el registrado en ML Developers")
    args = parser.parse_args()

    client_id = os.environ.get("ML_CLIENT_ID")
    client_secret = os.environ.get("ML_CLIENT_SECRET")
    if not client_id or not client_secret:
        print("Faltan ML_CLIENT_ID / ML_CLIENT_SECRET en el entorno.", file=sys.stderr)
        return 1

    if not args.redirect_uri.startswith("https://"):
        print("--redirect-uri debe ser https:// (Mercado Libre no acepta http://localhost).", file=sys.stderr)
        return 1

    auth_url, state = build_auth_url(client_id, args.redirect_uri)
    print(f"Abriendo el navegador para autorizar la app:\n{auth_url}\n")
    webbrowser.open(auth_url)

    code = input("Pegá acá el 'code' que te mostró la página de callback: ").strip()
    if not code:
        print("No se ingresó ningún code.", file=sys.stderr)
        return 1

    tokens = exchange_code(client_id, client_secret, code, args.redirect_uri)
    print("Autorización OK. Cargando ML_REFRESH_TOKEN en GitHub Secrets...")
    set_secret("ML_REFRESH_TOKEN", tokens.refresh_token, repo=args.repo)
    print(
        "Listo: ML_REFRESH_TOKEN cargado. El access_token de esta sesión expira en "
        f"{tokens.expires_in}s y no hace falta guardarlo — el workflow lo regenera solo."
    )
    print(f"\nPara correr el spike ahora mismo:\n  ML_ACCESS_TOKEN={tokens.access_token} uv run python -m ingest.meli_explore")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
