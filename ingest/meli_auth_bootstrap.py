"""Script de un solo uso: autoriza la app de Mercado Libre por navegador y
carga ML_REFRESH_TOKEN en GitHub Secrets.

Uso (ver README.md para el checklist completo):

    ML_CLIENT_ID=... ML_CLIENT_SECRET=... \\
        uv run python -m ingest.meli_auth_bootstrap [--repo owner/repo]

Requiere que ML_CLIENT_ID/ML_CLIENT_SECRET ya existan como variables de
entorno LOCALES (no hace falta que estén todavía en GitHub Secrets — de
hecho el resultado de este script es justamente lo que falta cargar ahí,
salvo ML_REFRESH_TOKEN que este mismo script sube).

Si Mercado Libre rechaza `redirect_uri=http://localhost:8080/callback` al
registrar la app, el plan B (documentado en el README) es registrar
site/oauth-callback.html como redirect_uri, abrir manualmente la URL de
autorización, copiar el `code` que la página muestra, y correr:

    ML_CLIENT_ID=... ML_CLIENT_SECRET=... \\
        uv run python -m ingest.meli_auth_bootstrap --code <code-copiado> \\
        --redirect-uri https://<usuario>.github.io/<repo>/oauth-callback.html
"""

from __future__ import annotations

import argparse
import http.server
import os
import sys
import threading
import urllib.parse
import webbrowser

from ingest.gh_secrets import set_secret
from ingest.meli_auth import build_auth_url, exchange_code

DEFAULT_REDIRECT_URI = "http://localhost:8080/callback"


class _CallbackResult:
    code: str | None = None
    state: str | None = None
    error: str | None = None


def _run_local_callback_server(expected_state: str, port: int) -> _CallbackResult:
    result = _CallbackResult()
    done = threading.Event()

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 (nombre impuesto por BaseHTTPRequestHandler)
            parsed = urllib.parse.urlparse(self.path)
            qs = urllib.parse.parse_qs(parsed.query)
            if "code" in qs:
                result.code = qs["code"][0]
                result.state = qs.get("state", [None])[0]
                body = b"Autorizado. Pod\xc3\xa9s cerrar esta pestana y volver a la terminal."
            else:
                result.error = qs.get("error", ["desconocido"])[0]
                body = b"Error de autorizacion. Volve a la terminal para el detalle."
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(body)
            done.set()

        def log_message(self, *_args: object) -> None:  # silencia el log default
            pass

    server = http.server.HTTPServer(("localhost", port), Handler)
    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()
    done.wait(timeout=300)
    server.server_close()

    if result.error:
        raise RuntimeError(f"Mercado Libre devolvió un error de autorización: {result.error}")
    if result.code is None:
        raise RuntimeError("Timeout esperando el callback de autorización (5 min).")
    if expected_state and result.state != expected_state:
        raise RuntimeError("El 'state' devuelto no coincide con el enviado — posible CSRF, abortando.")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=None, help="owner/repo; por defecto el del directorio actual")
    parser.add_argument("--redirect-uri", default=DEFAULT_REDIRECT_URI)
    parser.add_argument("--code", default=None, help="Plan B: pegar el code copiado a mano en vez de levantar el server local")
    args = parser.parse_args()

    client_id = os.environ.get("ML_CLIENT_ID")
    client_secret = os.environ.get("ML_CLIENT_SECRET")
    if not client_id or not client_secret:
        print("Faltan ML_CLIENT_ID / ML_CLIENT_SECRET en el entorno.", file=sys.stderr)
        return 1

    if args.code:
        code = args.code
    else:
        auth_url, state = build_auth_url(client_id, args.redirect_uri)
        print(f"Abriendo el navegador para autorizar la app:\n{auth_url}\n")
        webbrowser.open(auth_url)
        port = urllib.parse.urlparse(args.redirect_uri).port or 8080
        result = _run_local_callback_server(state, port)
        code = result.code

    tokens = exchange_code(client_id, client_secret, code, args.redirect_uri)
    print("Autorización OK. Cargando ML_REFRESH_TOKEN en GitHub Secrets...")
    set_secret("ML_REFRESH_TOKEN", tokens.refresh_token, repo=args.repo)
    print("Listo: ML_REFRESH_TOKEN cargado. El access_token de esta sesión expira en "
          f"{tokens.expires_in}s y no hace falta guardarlo — el workflow lo regenera solo.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
